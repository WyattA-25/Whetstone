"""Configurable optimization objective: what "better" means for a run.

Examples:
  Objective("success", "max")                                   # public demo: fix rate
  Objective("tokens", "min", [Constraint("success", ">=", -0.02, relative_to_baseline=True)])
      # employer pilot: fewer tokens, success may drop at most 2 points vs baseline
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean

from .adapter import Score


@dataclass(frozen=True)
class Constraint:
    metric: str
    op: str                          # ">=" or "<="
    value: float
    relative_to_baseline: bool = False   # if True, threshold = baseline[metric] + value

    def ok(self, agg: dict, baseline: dict | None) -> bool:
        thr = self.value + (baseline[self.metric] if self.relative_to_baseline and baseline else 0.0)
        v = agg[self.metric]
        return v >= thr - 1e-9 if self.op == ">=" else v <= thr + 1e-9


@dataclass(frozen=True)
class Objective:
    metric: str = "success"
    direction: str = "max"           # "max" or "min"
    constraints: list[Constraint] = field(default_factory=list)

    @staticmethod
    def aggregate(scores: list[Score]) -> dict[str, float]:
        keys = set().union(*(s.metrics for s in scores)) if scores else set()
        agg = {k: mean(s.metrics.get(k, 0.0) for s in scores) for k in keys}
        agg["n"] = len(scores)
        return agg

    def feasible(self, agg: dict, baseline: dict | None = None) -> bool:
        return all(c.ok(agg, baseline) for c in self.constraints)

    def fitness(self, agg: dict, baseline: dict | None = None) -> float:
        """Higher is always better. Infeasible candidates sort below every feasible one."""
        v = agg[self.metric] if self.direction == "max" else -agg[self.metric]
        return v if self.feasible(agg, baseline) else v - 1e9

    def describe(self) -> str:
        s = f"{self.direction}imize {self.metric}"
        for c in self.constraints:
            rel = " (vs baseline)" if c.relative_to_baseline else ""
            s += f", subject to {c.metric} {c.op} {c.value:+g}{rel}"
        return s

    @classmethod
    def from_dict(cls, d: dict) -> "Objective":
        return cls(d.get("metric", "success"), d.get("direction", "max"),
                   [Constraint(**c) for c in d.get("constraints", [])])
