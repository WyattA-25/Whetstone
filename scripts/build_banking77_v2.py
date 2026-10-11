"""Build the Banking77 v2 dataset (task "banking77").

- train (12/intent = 120) and val (8/intent = 80): stratified sample from Banking77's official TRAIN file
- held-out (40/intent = 400): ALL official Banking77 TEST examples for the 10 intents
- training texts that also appear in the test file (6 exact duplicates) are excluded

Source: PolyAI Banking77 (CC-BY-4.0), https://github.com/PolyAI-LDN/task-specific-datasets
Usage: python scripts/build_banking77_v2.py data/raw/banking77/train.csv data/raw/banking77/test.csv
"""
import csv
import json
import random
import sys
from pathlib import Path

INTENTS = [
    "pending_transfer", "failed_transfer", "declined_transfer", "cancel_transfer",
    "transfer_not_received_by_recipient", "transfer_timing", "balance_not_updated_after_bank_transfer",
    "pending_top_up", "top_up_failed", "top_up_reverted",
]
N_TRAIN, N_VAL = 12, 8
SEED = 42
OUT = Path("data/banking77/banking77_v2.jsonl")


def main(train_csv: str, test_csv: str) -> None:
    train = list(csv.DictReader(open(train_csv, encoding="utf-8")))
    test = list(csv.DictReader(open(test_csv, encoding="utf-8")))
    test_texts = {r["text"].strip().lower() for r in test}
    rng = random.Random(SEED)
    rows = []
    for intent in INTENTS:
        pool = sorted({r["text"].strip() for r in train
                       if r["category"] == intent and r["text"].strip().lower() not in test_texts})
        picked = rng.sample(pool, N_TRAIN + N_VAL)
        for i, t in enumerate(picked):
            part = "train" if i < N_TRAIN else "val"
            rows.append({"id": f"b77v2-{part}-{intent}-{i:02d}", "text": t, "label": intent, "part": part})
        for i, t in enumerate(sorted(r["text"].strip() for r in test if r["category"] == intent)):
            rows.append({"id": f"b77v2-heldout-{intent}-{i:02d}", "text": t, "label": intent, "part": "heldout"})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    counts = {p: sum(r["part"] == p for r in rows) for p in ("train", "val", "heldout")}
    print(f"wrote {len(rows)} examples to {OUT}: {counts}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
