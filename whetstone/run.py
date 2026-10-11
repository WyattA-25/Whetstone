"""The optimization loop. Resumable: state is saved after every round.

Usage:
  python -m whetstone.run --task classify --rounds 8
  python -m whetstone.run --task classify --objective tokens:min --constraint "success>=-0.02:rel"
  python -m whetstone.run --resume <run_id>
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .agents import analyze, propose
from .config import (AGENT_EXTRA_BODY, OPTIMIZER_MAX_USD_PER_RUN, EndpointConfig, optimizer_endpoint,
                     scoring_endpoint)
from .evaluate import evaluate_prompt
from .llm import BudgetExceeded, LLMClient, Usage
from .objective import Constraint, Objective
from .store import JsonlStore, Store, get_store
from .tasks import get_task, is_private, load_or_create_split

POPULATION = 4
N_FAILURES = 8


def combine(train: dict, val: dict) -> dict:
    """Example-weighted mean of train and val metrics."""
    n = train["n"] + val["n"]
    out = {k: (train.get(k, 0) * train["n"] + val.get(k, 0) * val["n"]) / n for k in set(train) | set(val) if k != "n"}
    out["n"] = n
    return out


def short(agg: dict | None, metric: str) -> str:
    if not agg:
        return "-"
    v = agg.get(metric, 0)
    return f"{v:.1%}" if metric == "success" else f"{v:.0f}" if metric == "tokens" else f"{v:.3g}"


class Runner:
    def __init__(self, state: dict, store: Store, run_dir: Path):
        self.s = state
        self.store = store
        self.run_dir = run_dir
        self.adapter = get_task(state["task"])
        self.examples = self.adapter.examples()
        self.split, _ = load_or_create_split(state["task"], self.adapter)
        assert self.split.heldout_hash == state["heldout_hash"], "split changed since this run started"
        self.train = self.split.train(self.examples)
        self.val = self.split.val(self.examples)
        self.objective = Objective.from_dict(state["objective"])
        self.opt = LLMClient(optimizer_endpoint(), max_usd=state["budgets"]["optimizer_usd"], timeout=90, attempts=3,
                             extra_body=AGENT_EXTRA_BODY)
        self.score_llm = LLMClient(self._scoring_endpoint(), max_usd=state["budgets"]["scoring_usd"], temperature=0,
                                   timeout=self.adapter.scoring_timeout, extra_body=self.adapter.scoring_extra_body)
        self.opt.usage = Usage(**{k: v for k, v in state["usage"]["optimizer"].items()})
        self.score_llm.usage = Usage(**{k: v for k, v in state["usage"]["scoring"].items()})

    def _scoring_endpoint(self) -> EndpointConfig:
        """The customer's own key (decrypted from KMS, in memory only) or, for internal runs, the default."""
        cust = self.s.get("customer")
        if not cust:
            return scoring_endpoint()
        from .accounts import Accounts
        k = Accounts().key_secret(cust["customer_id"], cust["key_id"])
        return EndpointConfig("scoring", k["api_key"], k["base_url"], k["model"],
                              k["price_in_per_m"], k["price_out_per_m"])

    def _bill(self) -> None:
        cust = self.s.get("customer")
        if not cust:
            return
        try:
            from .accounts import Accounts
            rec = Accounts().finish_run(cust["customer_id"], self.s["run_id"], cust["month"],
                                        stopped=self.s.get("stopped") or "interrupted",
                                        round_done=max(0, self.s.get("round_done", 0)),
                                        ours=asdict(self.opt.usage), theirs=asdict(self.score_llm.usage))
            self.log(f"usage recorded: counted={rec['counted']} overage=${rec['overage_usd']} "
                     f"ours ${rec['optimizer_usd']} theirs ~${rec['scoring_usd_est']}")
            if rec["counted"]:
                from .billing import put_event   # AWS App Monetization metering (idempotent on run_id)
                put_event(cust["customer_id"], self.s["run_id"])
                self.log("metered 1 optimization_run to AWS App Monetization")
        except Exception as e:  # billing bookkeeping must never lose the run's results
            self.log(f"WARNING: could not record usage ({type(e).__name__}); run results are saved")

    # ---- helpers -------------------------------------------------------------------------------
    def save(self) -> None:
        self.s["usage"] = {"optimizer": asdict(self.opt.usage), "scoring": asdict(self.score_llm.usage)}
        tmp = self.run_dir / "state.json.tmp"
        tmp.write_text(json.dumps(self.s, indent=2))
        tmp.replace(self.run_dir / "state.json")
        if not self.s.get("private"):
            self.store.put_state(self.s["run_id"], self.s)

    def fit(self, agg: dict, split: str) -> float:
        return self.objective.fitness(agg, self.s["baseline"][split])

    def eval(self, prompt: str, batch) -> tuple[dict, list[str]]:
        agg, res = evaluate_prompt(self.adapter, prompt, batch, self.score_llm, self.split)
        return agg, [sc.notes for _, sc in res if sc.notes]

    def log(self, msg: str) -> None:
        line = f"[{datetime.now():%H:%M:%S}] {msg}"
        print(line, flush=True)
        with (self.run_dir / "log.txt").open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    # ---- baseline ------------------------------------------------------------------------------
    def baseline(self) -> None:
        prompt = self.adapter.starting_prompts()[0]
        tr, fails = self.eval(prompt, self.train)
        self.s["baseline"] = {"train": tr}          # constraints are relative to baseline
        va, _ = self.eval(prompt, self.val)
        cand = {"id": "baseline", "round": 0, "strategy": "baseline", "parents": [], "prompt": prompt,
                "train": tr, "val": va, "combined": combine(tr, va)}
        cand["fitness"] = self.fit(tr, "train")
        self.s["baseline"] = {"train": tr, "val": va, "combined": cand["combined"], "prompt": prompt}
        self.s["champion"] = cand
        self.s["population"] = [cand]
        self.s["champion_failures"] = fails
        self.store.insert("candidates", {"run_id": self.s["run_id"], **cand, "status": "champion"})
        self.store.insert("rounds", self.round_doc(0, [cand], promoted=True))
        m = self.objective.metric
        self.log(f"round 0 (baseline): train {short(tr, m)}  val {short(va, m)}  "
                 f"| {short(tr, 'tokens')} tok/ex | scoring ${self.score_llm.usage.usd:.4f}")
        self.s["round_done"] = 0
        self.save()

    def round_doc(self, r: int, cands: list[dict], promoted: bool) -> dict:
        ch = self.s["champion"]
        return {"run_id": self.s["run_id"], "round": r, "at": datetime.now(timezone.utc).isoformat(),
                "champion_id": ch["id"], "champion_train": ch["train"], "champion_val": ch["val"],
                "champion_combined": ch["combined"], "promoted": promoted,
                "candidates": [{"id": c["id"], "strategy": c["strategy"], "train": c.get("train"),
                                "val": c.get("val")} for c in cands],
                "usage": {"optimizer": self.opt.usage.as_dict(), "scoring": self.score_llm.usage.as_dict()},
                "lessons": self.s.get("lessons", [])}

    # ---- one round -----------------------------------------------------------------------------
    def round(self, r: int) -> None:
        rng = random.Random(self.s["seed"] * 1000 + r)
        champ = self.s["champion"]
        fails = self.s["champion_failures"]
        sample = rng.sample(fails, min(N_FAILURES, len(fails)))

        # 1) analyst writes lessons from the champion's TRAIN failures (never held-out)
        try:
            self.s["lessons"] = analyze(self.opt, description=self.adapter.description, prompt=champ["prompt"],
                                        failures=sample, lessons=self.s.get("lessons", []))
        except BudgetExceeded:
            raise
        except Exception as e:  # analyst is advisory: keep last round's lessons
            self.log(f"analyst failed ({type(e).__name__}); keeping previous lessons")
        self.store.insert("lessons", {"run_id": self.s["run_id"], "round": r, "lessons": self.s["lessons"]})

        # 2) proposers in parallel
        m = self.objective.metric
        pop = sorted(self.s["population"], key=lambda c: c["fitness"], reverse=True)
        as_parent = lambda c: {"id": c["id"], "prompt": c["prompt"], "score": short(c["train"], m)}
        # 6 parallel agents: over-generate so a provider hiccup still leaves several candidates
        n = self.adapter.proposals_per_round
        n_fresh = 2 if n >= 6 else 1
        jobs = [("mutate", [as_parent(champ)])] * (n - n_fresh - 1) + [("fresh", [])] * n_fresh
        jobs.append(("crossover", [as_parent(pop[0]), as_parent(pop[1])]) if len(pop) >= 2
                    else ("mutate", [as_parent(champ)]))
        common = dict(description=self.adapter.description, objective=self.objective.describe(),
                      lessons=self.s["lessons"], reference_prompt=self.s["baseline"]["prompt"])

        job_fails = [rng.sample(fails, min(N_FAILURES, len(fails))) for _ in jobs]

        def do(i):
            try:
                return propose(self.opt, jobs[i][0], parents=jobs[i][1], failures=job_fails[i], **common)
            except BudgetExceeded:
                raise
            except Exception as e:  # one failed agent shouldn't sink the round
                self.log(f"{jobs[i][0]} proposer failed ({type(e).__name__}: {str(e)[:200]})")
                return None

        with ThreadPoolExecutor(len(jobs)) as ex:
            proposals = [p for p in ex.map(do, range(len(jobs))) if p]
        seen = {c["prompt"] for c in self.s["population"]}
        cands = []
        for i, p in enumerate(proposals):
            if p.prompt in seen:
                continue
            seen.add(p.prompt)
            cands.append({"id": f"r{r}-{p.strategy}-{i}", "round": r, "strategy": p.strategy,
                          "parents": p.parents, "prompt": p.prompt})

        # 3) evaluate candidates on this round's training batch, in parallel. With a minibatch (a fresh
        #    seeded sample each round, which resists overfitting a fixed train set), the champion is scored
        #    on the SAME batch so the comparison is paired, and the analyst gets fresh failures next round.
        mb = self.adapter.train_minibatch
        batch = rng.sample(self.train, mb) if mb and mb < len(self.train) else self.train
        paired = batch is not self.train and bool(cands)
        prompts = [c["prompt"] for c in cands] + ([champ["prompt"]] if paired else [])
        with ThreadPoolExecutor(max(1, len(prompts))) as ex:
            results = list(ex.map(lambda p: self.eval(p, batch), prompts))
        for c, (agg, f) in zip(cands, results):
            c["train"], c["fitness"], c["_fails"] = agg, self.fit(agg, "train"), f
        champ_bar = champ["fitness"]
        if paired:
            champ_bar = self.fit(results[-1][0], "train")
            self.s["champion_failures"] = results[-1][1]
            self.s["champion_batch"] = results[-1][0]

        # 4) selection: the top-2 candidates that beat the champion on the training batch get a validation
        #    check, and the champion is re-checked on validation in the same round. Its val score is a
        #    running mean over all checks, so one lucky measurement can't block every challenger (winner's
        #    curse). Promotion requires beating the champion on validation.
        challengers = sorted([c for c in cands if c["fitness"] > champ_bar],
                             key=lambda c: c["fitness"], reverse=True)[:2]
        promoted = None
        if challengers:
            with ThreadPoolExecutor(len(challengers) + 1) as ex:
                vals = list(ex.map(lambda p: self.eval(p, self.val)[0],
                                   [champ["prompt"]] + [c["prompt"] for c in challengers]))
            k = champ.get("val_runs", 1)
            champ["val"] = {m_: (champ["val"].get(m_, 0) * k + vals[0].get(m_, 0)) / (k + 1)
                            for m_ in vals[0] if m_ != "n"} | {"n": vals[0]["n"]}
            champ["val_runs"] = k + 1
            champ["combined"] = combine(champ["train"], champ["val"])
            for c, v in zip(challengers, vals[1:]):
                c["val"], c["combined"] = v, combine(c["train"], v)
                best = promoted or champ
                if self.fit(v, "val") > self.fit(best["val"], "val"):
                    promoted = c
        if promoted:
            self.s["champion"] = {k: v for k, v in promoted.items() if k != "_fails"}
            self.s["champion_failures"] = promoted["_fails"]

        # 5) keep the top variants, record everything
        for c in cands:
            status = "champion" if c is promoted else "kept" if c in challengers else "discarded"
            self.store.insert("candidates", {"run_id": self.s["run_id"],
                                             **{k: v for k, v in c.items() if k != "_fails"}, "status": status})
        pool = self.s["population"] + [{k: v for k, v in c.items() if k != "_fails"} for c in cands]
        self.s["population"] = sorted(pool, key=lambda c: c["fitness"], reverse=True)[:POPULATION]
        self.store.insert("rounds", self.round_doc(r, cands, promoted is not None))

        ch = self.s["champion"]
        cs = ", ".join(f"{c['strategy']} {short(c['train'], m)}" + (f" (val {short(c['val'], m)})" if c.get("val") else "")
                       for c in cands) or "no valid proposals"
        cs += f" [{len(proposals)}/{len(jobs)} proposals usable]"
        bar = f" (on this batch {short(self.s['champion_batch'], m)})" if paired and not promoted else ""
        self.log(f"round {r}: champion train {short(ch['train'], m)}{bar} val {short(ch['val'], m)}"
                 f"{'  << NEW CHAMPION ' + ch['id'] if promoted else ''} | candidates: {cs} "
                 f"| spend ours ${self.opt.usage.usd:.4f} theirs ${self.score_llm.usage.usd:.4f}")
        self.s["round_done"] = r
        self.save()

    def go(self) -> None:
        try:
            if self.s["round_done"] < 0:
                self.baseline()
            failures = 0
            while self.s["round_done"] < self.s["rounds"]:
                try:
                    self.round(self.s["round_done"] + 1)
                    failures = 0
                except (BudgetExceeded, KeyboardInterrupt):
                    raise
                except Exception as e:  # provider outage etc.: wait and retry the round from saved state
                    failures += 1
                    if failures > 5:
                        raise
                    self.log(f"round {self.s['round_done'] + 1} failed ({type(e).__name__}: {str(e)[:120]}); "
                             f"retry {failures}/5 in {30 * failures}s")
                    time.sleep(30 * failures)
            self.s["stopped"] = "completed"
        except BudgetExceeded as e:
            self.s["stopped"] = f"budget: {e}"     # incomplete round is discarded; best so far is kept
            self.log(f"stopping gracefully: {e}")
        except Exception as e:
            self.s["stopped"] = f"error: {type(e).__name__}"
            self.log(f"stopping after repeated errors: {e}; best so far is kept; resume with --resume {self.s['run_id']}")
        except KeyboardInterrupt:
            self.s["stopped"] = "interrupted"
            self.log("interrupted; resume with --resume " + self.s["run_id"])
        self.save()
        self._bill()
        ch, b, m = self.s.get("champion"), self.s.get("baseline"), self.objective.metric
        if ch and b:
            self.log(f"done ({self.s['stopped']}). baseline val {short(b['val'], m)} -> champion val "
                     f"{short(ch['val'], m)} [{ch['id']}]. Held-out is untouched until final eval.")


def parse_constraint(s: str) -> Constraint:
    m = re.fullmatch(r"(\w+)(>=|<=)([-+]?[0-9.]+)(:rel)?", s.replace(" ", ""))
    if not m:
        raise argparse.ArgumentTypeError(f"bad constraint {s!r}; use e.g. success>=-0.02:rel")
    return Constraint(m[1], m[2], float(m[3]), bool(m[4]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task")
    ap.add_argument("--rounds", type=int, help="default 8; on --resume, extends the run")
    ap.add_argument("--objective", default="success:max", help="metric:max|min")
    ap.add_argument("--constraint", action="append", type=parse_constraint, default=[])
    ap.add_argument("--max-usd-optimizer", type=float, default=OPTIMIZER_MAX_USD_PER_RUN)
    ap.add_argument("--max-usd-scoring", type=float, default=5.0, help="customer's per-run spending limit")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--resume")
    ap.add_argument("--run-id", help="explicit id for a new run (the web UI sets this)")
    ap.add_argument("--customer", help="customer id: score on that customer's stored API key")
    ap.add_argument("--key-id", help="which of the customer's keys to score with")
    ap.add_argument("--confirm-extra", action="store_true", help="customer confirmed the $5 extra-run charge")
    args = ap.parse_args()

    if args.resume:
        run_dir = Path("runs") / args.resume
        state = json.loads((run_dir / "state.json").read_text())
        store = JsonlStore("runs") if state.get("private") else get_store("runs")
        state["stopped"] = None
        if args.rounds:
            state["rounds"] = args.rounds
        print(f"resuming {args.resume} after round {state['round_done']}")
    else:
        if not args.task:
            ap.error("--task is required for a new run")
        # Confidential pilots stay on this machine: local files only, never DynamoDB/dashboard/results/.
        store = JsonlStore("runs") if is_private(args.task) else get_store("runs")
        metric, direction = args.objective.split(":")
        obj = Objective(metric, direction, args.constraint)
        adapter = get_task(args.task)
        split, _ = load_or_create_split(args.task, adapter)
        args.rounds = args.rounds or 8
        run_id = args.run_id or f"{args.task}-{datetime.now():%Y%m%d-%H%M%S}"
        run_dir = Path("runs") / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        state = {"run_id": run_id, "task": args.task, "rounds": args.rounds, "seed": args.seed,
                 "objective": {"metric": obj.metric, "direction": obj.direction,
                               "constraints": [asdict(c) for c in obj.constraints]},
                 "budgets": {"optimizer_usd": args.max_usd_optimizer, "scoring_usd": args.max_usd_scoring},
                 "heldout_hash": split.heldout_hash, "round_done": -1, "lessons": [],
                 "private": is_private(args.task),
                 "usage": {"optimizer": asdict(Usage()), "scoring": asdict(Usage())},
                 "models": {"optimizer": optimizer_endpoint().model, "scoring": scoring_endpoint().model},
                 "started_at": datetime.now(timezone.utc).isoformat()}
        if args.customer:
            from .accounts import Accounts, month
            acc = Accounts()
            quote = acc.quote_next_run(args.customer)
            if quote["next_is_extra"] and not args.confirm_extra:
                raise SystemExit(f"{quote['used']} of {quote['included']} included runs used: this run costs "
                                 f"${quote['extra_run_usd']:.0f}. Re-run with --confirm-extra to accept.")
            k = acc.key_secret(args.customer, args.key_id)        # fails fast if revoked; secret not kept
            state["models"]["scoring"] = k["model"]
            state["customer"] = {"customer_id": args.customer, "key_id": args.key_id, "month": month(),
                                 "extra": quote["next_is_extra"]}
            acc.start_run(args.customer, run_id, key_id=args.key_id, task=args.task,
                          max_usd=args.max_usd_scoring, extra=quote["next_is_extra"])
        store.insert("runs", {k: v for k, v in state.items() if k != "usage"})
        print(f"run {run_id}: {obj.describe()} | {args.rounds} rounds | budgets: ours ${args.max_usd_optimizer}, "
              f"theirs ${args.max_usd_scoring}")
    Runner(state, store, run_dir).go()


if __name__ == "__main__":
    main()
