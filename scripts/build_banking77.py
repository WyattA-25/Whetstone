"""Build the Banking77 subset used by the classification adapter.

Source: PolyAI Banking77 test split (CC-BY-4.0), https://github.com/PolyAI-LDN/task-specific-datasets
Usage: python scripts/build_banking77.py data/raw/banking77/test.csv
"""
import csv
import json
import random
import sys
from pathlib import Path

# Ten intents that are easy to confuse: pending vs failed vs declined vs reverted, transfer vs top-up.
INTENTS = [
    "pending_transfer", "failed_transfer", "declined_transfer", "cancel_transfer",
    "transfer_not_received_by_recipient", "transfer_timing", "balance_not_updated_after_bank_transfer",
    "pending_top_up", "top_up_failed", "top_up_reverted",
]
PER_INTENT = 20
SEED = 42
OUT = Path("data/classify/banking77_subset.jsonl")


def main(src: str) -> None:
    rows = list(csv.DictReader(open(src, encoding="utf-8")))
    rng = random.Random(SEED)
    out = []
    for intent in INTENTS:
        texts = sorted(r["text"].strip() for r in rows if r["category"] == intent)
        for i, t in enumerate(rng.sample(texts, PER_INTENT)):
            out.append({"id": f"b77-{intent}-{i:02d}", "text": t, "label": intent})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(r) + "\n" for r in out), encoding="utf-8")
    print(f"wrote {len(out)} examples to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
