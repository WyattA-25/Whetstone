"""The task adapter interface. The optimizer core only ever talks to tasks through this.

An adapter knows everything task-specific (code, scanners, labels...). The core knows
nothing about any of that: it just gets examples, runs prompts, and reads scores.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .llm import LLMClient


@dataclass(frozen=True)
class Example:
    id: str                      # stable, unique; used for the split hash
    input: Any                   # whatever the task needs
    expected: Any = None         # optional ground truth
    meta: dict = field(default_factory=dict)


@dataclass
class Output:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    usd: float = 0.0
    seconds: float = 0.0
    extra: dict = field(default_factory=dict)


@dataclass
class Score:
    """Per-example result. `metrics` are what objectives can optimize, e.g.
    {"success": 1.0, "tokens": 812, "seconds": 3.1, "usd": 0.0004}."""
    metrics: dict[str, float]
    notes: str = ""              # failure explanation for the analyst agent

    @property
    def success(self) -> float:
        return float(self.metrics.get("success", 0.0))


class TaskAdapter(ABC):
    name: str = "task"
    description: str = ""        # plain-language task description given to proposer agents
    scoring_timeout: float = 45.0    # seconds per scoring call attempt
    proposals_per_round: int = 6     # parallel proposer agents per round (fewer for expensive tasks)
    train_minibatch: int | None = None   # score candidates on a fresh seeded sample of train each round
    scoring_extra_body: dict | None = None  # provider options for scoring calls (the customer's model config)
    heldout_repeats: int = 3         # default repeats for the final held-out evaluation
    est_tokens_per_example: float = 500  # for the pre-run cost estimate (prompt + output, averaged over a run)

    def split_assignment(self) -> dict[str, list[str]] | None:
        """Optional fixed split {"train": ids, "val": ids, "heldout": ids}, e.g. an official test set.
        None means the core makes a seeded random split."""
        return None

    @abstractmethod
    def starting_prompts(self) -> list[str]:
        """The prompt(s) the customer uses today. The first one is the baseline."""

    @abstractmethod
    def examples(self) -> list[Example]:
        """All examples. The core splits them into train / validation / held-out."""

    @abstractmethod
    def run(self, prompt: str, example: Example, llm: LLMClient) -> Output:
        """Execute the prompt on one example (on the customer's scoring key)."""

    @abstractmethod
    def score(self, example: Example, output: Output) -> Score:
        """Score one output. Must include "success"; tokens/seconds/usd are added by the core if absent."""

    def evaluate(self, prompt: str, example: Example, llm: LLMClient) -> Score:
        out = self.run(prompt, example, llm)
        s = self.score(example, out)
        s.metrics.setdefault("tokens", out.prompt_tokens + out.completion_tokens)
        s.metrics.setdefault("seconds", out.seconds)
        s.metrics.setdefault("usd", out.usd)
        return s
