"""Adapter A: support-ticket intent classification (Banking77 subset), scored by exact match.

Small, cheap, and nothing to do with code: it shows the optimizer is general.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..adapter import Example, Output, Score, TaskAdapter
from ..llm import LLMClient

DATA = Path("data/classify/banking77_subset.jsonl")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9_]+", " ", s.lower().replace("-", "_")).strip()


class ClassifyAdapter(TaskAdapter):
    name = "classify"
    description = ("Classify a bank customer's support message into exactly one intent label. "
                   "The prompt is used as the system message; the customer message is the user message. "
                   "The model's reply is parsed for the label, so the prompt must list the valid labels "
                   "and the reply should contain exactly one of them.")

    def __init__(self, path: Path = DATA):
        self.path = path
        self._rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        self.labels = sorted({r["label"] for r in self._rows})

    def starting_prompts(self) -> list[str]:
        # Deliberately plain, like a first version someone would actually ship.
        return ["Classify the customer's message into one of these categories:\n"
                + "\n".join(self.labels)
                + "\n\nRespond with the category name only."]

    def examples(self) -> list[Example]:
        return [Example(id=r["id"], input=r["text"], expected=r["label"]) for r in self._rows]

    def run(self, prompt: str, example: Example, llm: LLMClient) -> Output:
        r = llm.chat([{"role": "system", "content": prompt},
                      {"role": "user", "content": example.input}], temperature=0, max_tokens=1024)
        return Output(r.text, r.prompt_tokens, r.completion_tokens, r.usd, r.seconds)

    def parse(self, text: str) -> str | None:
        t = _norm(text)
        if t in self.labels:
            return t
        found = {lab for lab in self.labels if re.search(rf"(?<![a-z0-9_]){lab}(?![a-z0-9_])", t)}
        return found.pop() if len(found) == 1 else None

    def score(self, example: Example, output: Output) -> Score:
        pred = self.parse(output.text)
        ok = pred == example.expected
        notes = "" if ok else (f"message: {example.input!r}\nexpected: {example.expected}\n"
                               f"got: {pred or 'UNPARSEABLE'} (raw reply: {output.text.strip()[:120]!r})")
        return Score({"success": float(ok)}, notes)


class Banking77Adapter(ClassifyAdapter):
    """v2: train/val from Banking77's official train file, held-out = all 400 official test examples
    for the 10 intents. Scored with the model's thinking OFF, as a production classifier usually runs."""
    name = "banking77"
    proposals_per_round = 4
    train_minibatch = 60
    scoring_extra_body = {"thinking": {"type": "disabled"}}
    est_tokens_per_example = 250   # measured: ~95 at baseline, ~280 once prompts gain definitions
    heldout_repeats = 1      # 400 examples: per-example noise averages out; keeps the eval inside the rate limit

    def __init__(self, path: Path = Path("data/banking77/banking77_v2.jsonl")):
        super().__init__(path)

    def split_assignment(self) -> dict[str, list[str]]:
        return {p: [r["id"] for r in self._rows if r["part"] == p] for p in ("train", "val", "heldout")}
