"""Storage for runs, rounds, candidates, scores, lessons, usage.

JsonlStore writes to runs/<run_id>/<collection>.jsonl (works offline, easy to inspect).
A MongoStore with the same interface is added in step 7.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Protocol


class Store(Protocol):
    def insert(self, collection: str, doc: dict) -> None: ...
    def find(self, collection: str, **match) -> list[dict]: ...


class JsonlStore:
    def __init__(self, root: str | Path = "runs"):
        self.root = Path(root)
        self._lock = threading.Lock()

    def _path(self, collection: str, run_id: str) -> Path:
        p = self.root / run_id / f"{collection}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def insert(self, collection: str, doc: dict) -> None:
        with self._lock, self._path(collection, doc["run_id"]).open("a", encoding="utf-8") as f:
            f.write(json.dumps(doc, default=str) + "\n")

    def find(self, collection: str, **match) -> list[dict]:
        run_ids = [match["run_id"]] if "run_id" in match else [p.name for p in self.root.glob("*") if p.is_dir()]
        out = []
        for rid in run_ids:
            p = self.root / rid / f"{collection}.jsonl"
            if not p.exists():
                continue
            for line in p.read_text(encoding="utf-8").splitlines():
                doc = json.loads(line)
                if all(doc.get(k) == v for k, v in match.items()):
                    out.append(doc)
        return out
