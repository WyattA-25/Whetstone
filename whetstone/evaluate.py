"""Score one prompt on a batch of examples, in parallel."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from .adapter import Example, Score, TaskAdapter
from .config import MAX_CONCURRENCY
from .llm import BudgetExceeded, LLMClient
from .objective import Objective
from .split import Split


def evaluate_prompt(adapter: TaskAdapter, prompt: str, examples: list[Example], llm: LLMClient,
                    split: Split, *, final_eval: bool = False) -> tuple[dict, list[tuple[Example, Score]]]:
    """Returns (aggregate metrics, [(example, score)]). Refuses held-out examples unless final_eval."""
    if not final_eval:
        split.assert_not_heldout(examples)

    def one(ex: Example) -> Score:
        err = None
        for _ in range(3):  # infra errors (timeouts, exhausted 429 retries) are retried, not scored as failures
            try:
                s = adapter.evaluate(prompt, ex, llm)
                s.metrics.setdefault("error", 0.0)
                return s
            except BudgetExceeded:
                raise
            except Exception as e:
                err = e
        # Still failing: count it, and report the error rate so it can't silently move a score.
        return Score({"success": 0.0, "error": 1.0}, f"error: {type(err).__name__}: {str(err)[:200]}")

    with ThreadPoolExecutor(MAX_CONCURRENCY) as ex:
        scores = list(ex.map(one, examples))
    return Objective.aggregate(scores), list(zip(examples, scores))
