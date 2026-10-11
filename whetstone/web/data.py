"""Read-side access to run data for the web UI: local files or DynamoDB (same shapes either way).

Private runs (private pilot: state "private": true, or a task starting with "pilot") are never returned.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from ..store import DynamoStore, JsonlStore

RUNS = Path(os.getenv("WHETSTONE_RUNS_DIR", "runs"))


def _source() -> str:
    return os.getenv("WHETSTONE_UI_SOURCE") or ("dynamo" if os.getenv("WHETSTONE_STORE") == "dynamo" else "local")


def _private(state: dict) -> bool:
    return bool(state.get("private")) or str(state.get("task", "")).startswith("pilot")


def _metric(agg: dict | None, m: str) -> float | None:
    return None if not agg else agg.get(m)


def summarize(st: dict) -> dict:
    m = st["objective"]["metric"]
    b, ch = st.get("baseline") or {}, st.get("champion") or {}
    return {"run_id": st["run_id"], "task": st["task"], "round_done": st.get("round_done", -1),
            "rounds": st.get("rounds"), "stopped": st.get("stopped"), "started_at": st.get("started_at"),
            "objective": st["objective"], "models": st.get("models"), "heldout_hash": st.get("heldout_hash"),
            "baseline": {"train": _metric(b.get("train"), m), "val": _metric(b.get("val"), m),
                         "tokens": _metric(b.get("val"), "tokens"), "prompt": b.get("prompt")},
            "champion": {"id": ch.get("id"), "train": _metric(ch.get("train"), m), "val": _metric(ch.get("val"), m),
                         "val_runs": ch.get("val_runs", 1), "tokens": _metric(ch.get("val"), "tokens"),
                         "prompt": ch.get("prompt"), "strategy": ch.get("strategy")},
            "usage": st.get("usage"), "lessons": st.get("lessons", [])}


class RunReader:
    def __init__(self) -> None:
        self.source = _source()
        self.local = JsonlStore(RUNS)
        self.dynamo = DynamoStore() if self.source == "dynamo" else None

    def _state(self, run_id: str) -> dict | None:
        if self.dynamo:
            return self.dynamo.get_state(run_id)
        p = RUNS / run_id / "state.json"
        return json.loads(p.read_text()) if p.exists() else None

    def list_runs(self) -> list[dict]:
        if self.dynamo:
            ids = sorted({d["run_id"] for d in self.dynamo.find("runs")})
        else:
            ids = sorted(p.name for p in RUNS.glob("*") if (p / "state.json").exists())
        out = []
        for rid in ids:
            st = self._state(rid)
            if st and not _private(st) and st.get("baseline"):
                out.append({k: v for k, v in summarize(st).items() if k not in ("baseline", "champion", "lessons")}
                           | {"metric": st["objective"]["metric"],
                              "baseline_val": summarize(st)["baseline"]["val"],
                              "champion_val": summarize(st)["champion"]["val"]})
        return sorted(out, key=lambda r: r.get("started_at") or "", reverse=True)

    def get_run(self, run_id: str) -> dict | None:
        st = self._state(run_id)
        if not st or _private(st):
            return None
        store = self.dynamo or self.local
        rounds = store.find("rounds", run_id=run_id)
        cands = store.find("candidates", run_id=run_id)
        heldout = store.find("heldout", run_id=run_id)
        # keep the latest record per round (a resumed run may have re-logged a round)
        by_round = {r["round"]: r for r in rounds}
        return {"summary": summarize(st),
                "rounds": [by_round[k] for k in sorted(by_round)],
                "candidates": [{k: c.get(k) for k in ("id", "round", "strategy", "parents", "prompt", "train",
                                                      "val", "status")} for c in cands],
                "heldout": ({k: v for k, v in heldout[-1].items() if k != "per_example"} if heldout else None)}
