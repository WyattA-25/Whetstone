"""Final evaluation: baseline vs best prompt on the frozen held-out set (never used during optimization).

Usage: python -m whetstone.final_eval <run_id> [--repeats 3]

- Verifies the held-out hash against the split file AND the hash recorded when the run started.
- Scores both prompts `repeats` times (the model is nondeterministic even at temperature 0) and averages
  per example, then compares them example-by-example (paired) with a bootstrap 95% confidence interval.
- Writes results/<run_id>-heldout.json and stores the result (DynamoDB too when enabled).
"""
from __future__ import annotations

import argparse
import json
import random
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from .config import scoring_endpoint
from .evaluate import evaluate_prompt
from .llm import LLMClient
from .objective import Objective
from .store import JsonlStore, get_store
from .tasks import get_task, load_or_create_split

METRICS = ("success", "tokens", "seconds", "usd", "error")


def bootstrap_ci(values: list[float], n: int = 10000, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    k = len(values)
    means = sorted(sum(values[rng.randrange(k)] for _ in range(k)) / k for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def per_example(adapter, prompt, examples, llm, split, repeats) -> tuple[dict[str, dict[str, float]], list[dict]]:
    """Returns ({example_id: {metric: mean over repeats}}, [aggregate per repeat])."""
    vals: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    aggs = []
    for _ in range(repeats):
        _, res = evaluate_prompt(adapter, prompt, examples, llm, split, final_eval=True)
        by_id = {ex.id: (ex, sc) for ex, sc in res}
        # Provider errors (429/503) are infrastructure, not wrong answers: retry them, never score them as 0.
        for attempt in range(4):
            errs = [ex for ex, sc in by_id.values() if sc.metrics.get("error")]
            if not errs:
                break
            print(f"  retrying {len(errs)} provider errors (pass {attempt + 1})", flush=True)
            time.sleep(15 * (attempt + 1))
            _, res2 = evaluate_prompt(adapter, prompt, errs, llm, split, final_eval=True)
            by_id.update({ex.id: (ex, sc) for ex, sc in res2})
        aggs.append(Objective.aggregate([sc for _, sc in by_id.values() if not sc.metrics.get("error")]))
        for ex, sc in by_id.values():
            for m, v in sc.metrics.items():
                vals[ex.id][m].append(v)
    return {eid: {m: mean(v) for m, v in d.items()} for eid, d in vals.items()}, aggs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--repeats", type=int, help="default: the task's heldout_repeats")
    args = ap.parse_args()

    run_dir = Path("runs") / args.run_id
    st = json.loads((run_dir / "state.json").read_text())
    adapter = get_task(st["task"])
    split, _ = load_or_create_split(st["task"], adapter)
    split.verify()
    if split.heldout_hash != st["heldout_hash"]:
        raise SystemExit("held-out hash differs from the one recorded when this run started; refusing to evaluate")
    args.repeats = args.repeats or adapter.heldout_repeats
    objective = Objective.from_dict(st["objective"])
    m = objective.metric
    heldout = split.heldout(adapter.examples(), final_eval=True)

    base_prompt, best = st["baseline"]["prompt"], st["champion"]
    print(f"HELD-OUT EVALUATION  run {args.run_id}  ({len(heldout)} examples never used in optimization, "
          f"{args.repeats} repeats per prompt)")
    print(f"held-out hash {split.heldout_hash[:12]}... verified against split file and run record")
    print(f"comparing baseline vs best prompt {best['id']}: {objective.describe()}\n")

    llm = LLMClient(scoring_endpoint(), temperature=0, timeout=adapter.scoring_timeout,
                    extra_body=adapter.scoring_extra_body)
    base, base_aggs = per_example(adapter, base_prompt, heldout, llm, split, args.repeats)
    champ, champ_aggs = per_example(adapter, best["prompt"], heldout, llm, split, args.repeats)
    # Anything still erroring after retries is excluded from BOTH prompts, and reported.
    excluded = sorted(i for i in base if base[i].get("error", 0) > 0 or champ.get(i, {}).get("error", 0) > 0)
    ids = sorted(i for i in base if i not in excluded)
    if excluded:
        print(f"WARNING: {len(excluded)} examples still failing with provider errors were excluded from both prompts")

    def summary(d: dict, aggs: list[dict]) -> dict:
        out = {}
        for k in METRICS:
            xs = [d[i].get(k, 0.0) for i in ids]
            lo, hi = bootstrap_ci(xs)
            out[k] = {"mean": mean(xs), "ci95": [lo, hi], "per_repeat": [a.get(k, 0.0) for a in aggs]}
        return out

    b, c = summary(base, base_aggs), summary(champ, champ_aggs)
    diffs = [champ[i].get(m, 0.0) - base[i].get(m, 0.0) for i in ids]
    d_lo, d_hi = bootstrap_ci(diffs)
    d_mean = mean(diffs)
    better = d_mean > 0 if objective.direction == "max" else d_mean < 0
    significant = (d_lo > 0) if objective.direction == "max" else (d_hi < 0)
    rel = d_mean / b[m]["mean"] if b[m]["mean"] else float("nan")

    pct = lambda x: f"{x:.1%}"
    fmt = {"success": pct, "tokens": lambda x: f"{x:.0f}", "seconds": lambda x: f"{x:.2f}s", "usd": lambda x: f"${x:.6f}"}
    print(f"{'':12s}{'baseline':>28s}{'best (' + best['id'] + ')':>32s}")
    for k in METRICS[:-1]:
        f = fmt[k]
        print(f"{k:12s}{f(b[k]['mean']):>12s} [{f(b[k]['ci95'][0])}, {f(b[k]['ci95'][1])}]"
              f"{f(c[k]['mean']):>16s} [{f(c[k]['ci95'][0])}, {f(c[k]['ci95'][1])}]")
    spread = lambda s: f"{min(s[m]['per_repeat']):.1%}-{max(s[m]['per_repeat']):.1%}" if m == "success" else ""
    print(f"\nrepeat-to-repeat spread on {m}: baseline {spread(b)}, best {spread(c)}")
    sign = "+" if d_mean >= 0 else ""
    print(f"paired difference in {m}: {sign}{d_mean * (100 if m == 'success' else 1):.1f}"
          f"{' pts' if m == 'success' else ''}  [95% CI {d_lo * (100 if m == 'success' else 1):+.1f}, "
          f"{d_hi * (100 if m == 'success' else 1):+.1f}]")
    print(f"relative improvement: {rel:+.1%}", end="")
    if m == "success" and b[m]["mean"] < 1:
        err_cut = (c[m]["mean"] - b[m]["mean"]) / (1 - b[m]["mean"])
        print(f"   |   error rate reduced by {err_cut:.0%}", end="")
    print()
    verdict = ("improvement is statistically significant at 95% (CI excludes zero)" if better and significant else
               "improvement is NOT significant at 95% with this sample; report as directional only" if better else
               "no improvement on held-out data")
    print(f"verdict: {verdict}")

    result = {"run_id": args.run_id, "task": st["task"], "at": datetime.now(timezone.utc).isoformat(),
              "objective": st["objective"], "n_heldout": len(ids), "excluded_for_errors": excluded, "repeats": args.repeats,
              "heldout_hash": split.heldout_hash, "best_id": best["id"], "baseline": b, "best": c,
              "paired_diff": {"metric": m, "mean": d_mean, "ci95": [d_lo, d_hi]}, "relative_improvement": rel,
              "significant": bool(better and significant), "verdict": verdict,
              "models": st.get("models"), "scoring_usage": llm.usage.as_dict(),
              "best_prompt": best["prompt"], "baseline_prompt": base_prompt,
              "per_example": {i: {"baseline": base[i], "best": champ[i]} for i in ids}}
    private = bool(st.get("private"))
    out_dir = Path("pilot/results") if private else Path("results")   # pilot results never enter the repo
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{args.run_id}-heldout.json"
    out.write_text(json.dumps(result, indent=2))
    (JsonlStore("runs") if private else get_store()).insert("heldout", result)
    print(f"\nsaved {out}  | held-out scoring cost ${llm.usage.usd:.4f} ({llm.usage.calls} calls)")


if __name__ == "__main__":
    main()
