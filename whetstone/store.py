"""Storage for runs, rounds, candidates, lessons, and run state.

- JsonlStore: runs/<run_id>/<collection>.jsonl. Works offline; the local source of truth.
- DynamoStore: AWS DynamoDB table (partition key run_id, sort key "<collection>#<seq>"). Each item holds
  the document as a JSON string, so nested dicts and floats need no conversion. The web UI reads from here.
- TeeStore: writes locally first, then to DynamoDB with the SAME sequence number, so `python -m
  whetstone.sync` can safely backfill anything that failed to upload (it overwrites identical keys).

Pick with WHETSTONE_STORE=local|dynamo (dynamo means local + DynamoDB).
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Protocol

RUNS_TABLE = os.getenv("DYNAMO_RUNS_TABLE", "whetstone-runs")
ACCOUNTS_TABLE = os.getenv("DYNAMO_ACCOUNTS_TABLE", "whetstone-accounts")


class Store(Protocol):
    def insert(self, collection: str, doc: dict) -> int | None: ...
    def find(self, collection: str, **match) -> list[dict]: ...
    def put_state(self, run_id: str, state: dict) -> None: ...


def _matches(doc: dict, match: dict) -> bool:
    return all(doc.get(k) == v for k, v in match.items())


class JsonlStore:
    def __init__(self, root: str | Path = "runs"):
        self.root = Path(root)
        self._lock = threading.Lock()
        self._counts: dict[Path, int] = {}

    def _path(self, collection: str, run_id: str) -> Path:
        p = self.root / run_id / f"{collection}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def insert(self, collection: str, doc: dict) -> int:
        """Appends the doc; returns its 0-based line index (used as the shared sequence number)."""
        p = self._path(collection, doc["run_id"])
        with self._lock:
            if p not in self._counts:
                self._counts[p] = len(p.read_text(encoding="utf-8").splitlines()) if p.exists() else 0
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(doc, default=str) + "\n")
            self._counts[p] += 1
            return self._counts[p] - 1

    def find(self, collection: str, **match) -> list[dict]:
        run_ids = [match["run_id"]] if "run_id" in match else [p.name for p in self.root.glob("*") if p.is_dir()]
        out = []
        for rid in run_ids:
            p = self.root / rid / f"{collection}.jsonl"
            if p.exists():
                out += [d for d in map(json.loads, p.read_text(encoding="utf-8").splitlines()) if _matches(d, match)]
        return out

    def put_state(self, run_id: str, state: dict) -> None:
        pass  # the runner writes runs/<run_id>/state.json itself


class DynamoStore:
    def __init__(self, table: str = RUNS_TABLE, region: str | None = None):
        import boto3
        self.table = boto3.resource("dynamodb", region_name=region or os.getenv("AWS_REGION", "us-east-1")).Table(table)

    @staticmethod
    def _item(run_id: str, sk: str, collection: str, doc: dict) -> dict:
        return {"run_id": run_id, "sk": sk, "collection": collection, "doc": json.dumps(doc, default=str)}

    def insert(self, collection: str, doc: dict, seq: int | None = None) -> None:
        seq = time.time_ns() if seq is None else seq
        self.table.put_item(Item=self._item(doc["run_id"], f"{collection}#{seq:020d}", collection, doc))

    def put_state(self, run_id: str, state: dict) -> None:
        self.table.put_item(Item=self._item(run_id, "state#latest", "state", state))

    def get_state(self, run_id: str) -> dict | None:
        it = self.table.get_item(Key={"run_id": run_id, "sk": "state#latest"}).get("Item")
        return json.loads(it["doc"]) if it else None

    def find(self, collection: str, **match) -> list[dict]:
        from boto3.dynamodb.conditions import Attr, Key
        if "run_id" in match:
            kw = {"KeyConditionExpression": Key("run_id").eq(match["run_id"]) & Key("sk").begins_with(f"{collection}#")}
            call = self.table.query
        else:
            kw = {"FilterExpression": Attr("collection").eq(collection)}
            call = self.table.scan
        items = []
        while True:
            r = call(**kw)
            items += r["Items"]
            if "LastEvaluatedKey" not in r:
                break
            kw["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        items.sort(key=lambda i: (i["run_id"], i["sk"]))
        return [d for d in (json.loads(i["doc"]) for i in items) if _matches(d, match)]


class TeeStore:
    """Local first (never lost), then DynamoDB. A DynamoDB outage never stops a run."""

    def __init__(self, local: JsonlStore, remote: DynamoStore, log=print):
        self.local, self.remote, self.log = local, remote, log
        self._last_warn = 0.0

    def _warn(self, e: Exception) -> None:
        if time.time() - self._last_warn > 60:
            self._last_warn = time.time()
            self.log(f"DynamoDB write failed ({type(e).__name__}: {str(e)[:120]}); kept locally, "
                     f"backfill later with: python -m whetstone.sync")

    def insert(self, collection: str, doc: dict) -> int:
        seq = self.local.insert(collection, doc)
        try:
            self.remote.insert(collection, doc, seq=seq)
        except Exception as e:
            self._warn(e)
        return seq

    def find(self, collection: str, **match) -> list[dict]:
        return self.local.find(collection, **match)

    def put_state(self, run_id: str, state: dict) -> None:
        try:
            self.remote.put_state(run_id, state)
        except Exception as e:
            self._warn(e)


def get_store(root: str | Path = "runs") -> Store:
    if os.getenv("WHETSTONE_STORE", "local") == "dynamo":
        return TeeStore(JsonlStore(root), DynamoStore())
    return JsonlStore(root)
