"""Score a task's starting prompt on train + validation: the "before" number.

Usage: python -m whetstone.baseline --task classify
"""
from __future__ import annotations

import argparse

from .config import scoring_endpoint
from .evaluate import evaluate_prompt
from .llm import LLMClient
from .tasks import get_task, load_or_create_split, split_path


def fmt(agg: dict) -> str:
    return (f"success {agg.get('success', 0):.1%}  |  {agg.get('tokens', 0):.0f} tok/ex  |  "
            f"{agg.get('seconds', 0):.2f} s/ex  |  ${agg.get('usd', 0):.6f}/ex  |  "
            f"errors {agg.get('error', 0) * agg['n']:.0f}  (n={agg['n']})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True)
    args = ap.parse_args()

    adapter = get_task(args.task)
    examples = adapter.examples()
    split, created = load_or_create_split(args.task, adapter)
    print(f"split {'CREATED and frozen' if created else 'loaded + verified'}: {split_path(args.task)}")
    print(f"  train={len(split.train_ids)} val={len(split.val_ids)} heldout={len(split.heldout_ids)}")
    print(f"  heldout hash: {split.heldout_hash}")

    llm = LLMClient(scoring_endpoint(), temperature=0, timeout=adapter.scoring_timeout)
    prompt = adapter.starting_prompts()[0]
    for name, batch in (("train", split.train(examples)), ("val", split.val(examples))):
        agg, _ = evaluate_prompt(adapter, prompt, batch, llm, split)
        print(f"baseline {name:5s}: {fmt(agg)}")
    print(f"scoring account usage: {llm.usage.as_dict()}")


if __name__ == "__main__":
    main()
