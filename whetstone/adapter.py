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
