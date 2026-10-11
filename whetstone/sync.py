"""Upload local runs to DynamoDB (idempotent: same keys are overwritten, never duplicated).

Usage: python -m whetstone.sync <run_id> [<run_id> ...]
       python -m whetstone.sync --all
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from .store import DynamoStore

load_dotenv()


def sync_run(ddb: DynamoStore, run_dir: Path) -> int:
    n = 0
    with ddb.table.batch_writer(overwrite_by_pkeys=["run_id", "sk"]) as bw:
        for f in sorted(run_dir.glob("*.jsonl")):
            for i, line in enumerate(f.read_text(encoding="utf-8").splitlines()):
                doc = json.loads(line)
                bw.put_item(Item=ddb._item(doc["run_id"], f"{f.stem}#{i:020d}", f.stem, doc))
                n += 1
        st = run_dir / "state.json"
        if st.exists():
            bw.put_item(Item=ddb._item(run_dir.name, "state#latest", "state", json.loads(st.read_text())))
            n += 1
    return n


def main() -> None:
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    runs = [p for p in Path("runs").glob("*") if p.is_dir()] if "--all" in args else [Path("runs") / a for a in args]
    ddb = DynamoStore()
    for r in runs:
        print(f"{r.name}: {sync_run(ddb, r)} items uploaded")


if __name__ == "__main__":
    main()
