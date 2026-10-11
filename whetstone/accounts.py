"""Customer accounts: plans, run counter, usage log, and customer API keys (encrypted with AWS KMS).

Business rules (see README "Business model"):
- Our agents run on our Luminal account. Scoring runs on the CUSTOMER's own AI-provider key.
- Standard $199/mo with 10 runs, Founding $49/mo (locked 12 months) with 4 runs; extra runs $5 each.
  Unused runs don't roll over (counter is per calendar month, UTC).
- A run counts unless it failed because of our bug; a cancelled run counts only if >1 round finished.
- Customer keys: encrypted at rest with KMS (ciphertext bound to customer + key id), never logged, never
  returned to the browser, revocable any time, validated with one tiny call when added.

Storage: DynamoDB table whetstone-accounts, partition key customer_id, sort key sk:
  "profile" | "key#<key_id>" | "usage#<YYYY-MM>#<run_id>"
"""
from __future__ import annotations

import base64
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from dotenv import load_dotenv

from .store import ACCOUNTS_TABLE

load_dotenv()

PLANS = {
    "standard": {"name": "Standard", "usd_per_month": 199, "included_runs": 10, "locked_months": 0},
    "founding": {"name": "Founding customer", "usd_per_month": 49, "included_runs": 4, "locked_months": 12},
}
EXTRA_RUN_USD = 5.0
DEMO_CUSTOMER = "demo"
KMS_ALIAS = os.getenv("KMS_KEY_ALIAS", "alias/whetstone-customer-keys")
REGION = os.getenv("AWS_REGION", "us-east-1")


def month(ts: datetime | None = None) -> str:
    return (ts or datetime.now(timezone.utc)).strftime("%Y-%m")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def counts_as_run(stopped: str | None, round_done: int) -> bool:
    """completed / budget stop -> counts. Our error -> doesn't. Cancelled -> only if >1 round finished."""
    if stopped is None:
        return False
    if stopped.startswith("error"):
        return False
    if stopped == "interrupted":
        return round_done > 1
    return True


class KeyVault:
    """Envelope-free direct KMS encryption: API keys are tiny (<4 KB), so KMS encrypts them directly."""

    def __init__(self) -> None:
        self.kms = boto3.client("kms", region_name=REGION)

    def encrypt(self, plaintext: str, customer_id: str, key_id: str) -> str:
        r = self.kms.encrypt(KeyId=KMS_ALIAS, Plaintext=plaintext.encode(),
                             EncryptionContext={"customer_id": customer_id, "key_id": key_id})
        return base64.b64encode(r["CiphertextBlob"]).decode()

    def decrypt(self, blob: str, customer_id: str, key_id: str) -> str:
        r = self.kms.decrypt(CiphertextBlob=base64.b64decode(blob),
                             EncryptionContext={"customer_id": customer_id, "key_id": key_id})
        return r["Plaintext"].decode()


def validate_key(base_url: str, model: str, api_key: str) -> tuple[bool, str]:
    """One tiny call. Error messages are reduced to type + status so a key can never be echoed back."""
    from openai import OpenAI, RateLimitError
    try:
        c = OpenAI(api_key=api_key, base_url=base_url or None, timeout=30, max_retries=3)
        c.chat.completions.create(model=model, messages=[{"role": "user", "content": "ping"}], max_tokens=5)
        return True, "ok"
    except RateLimitError:  # 429 comes after authentication: the key is accepted, the provider is just busy
        return True, "ok (provider busy, key accepted)"
    except Exception as e:  # noqa: BLE001 - sanitized below
        status = getattr(e, "status_code", None)
        return False, f"{type(e).__name__}{f' (HTTP {status})' if status else ''}"


class Accounts:
    def __init__(self) -> None:
        self.table = boto3.resource("dynamodb", region_name=REGION).Table(ACCOUNTS_TABLE)
        self.vault = KeyVault()

    # ---- profile / plan -----------------------------------------------------------------------
    def profile(self, cid: str) -> dict:
        it = self.table.get_item(Key={"customer_id": cid, "sk": "profile"}).get("Item")
        if not it:
            it = {"customer_id": cid, "sk": "profile", "plan": "founding", "created_at": now()}
            self.table.put_item(Item=it)
        return {"customer_id": cid, "plan": it["plan"], "created_at": it["created_at"]}

    def set_plan(self, cid: str, plan: str) -> dict:
        if plan not in PLANS:
            raise ValueError(f"unknown plan {plan!r}")
        self.profile(cid)
        self.table.update_item(Key={"customer_id": cid, "sk": "profile"},
                               UpdateExpression="SET #p = :p, plan_set_at = :t",
                               ExpressionAttributeNames={"#p": "plan"},
                               ExpressionAttributeValues={":p": plan, ":t": now()})
        return self.profile(cid)

    # ---- API keys -----------------------------------------------------------------------------
    def add_key(self, cid: str, *, provider: str, base_url: str, model: str, api_key: str,
                price_in_per_m: float, price_out_per_m: float) -> dict:
        api_key = api_key.strip()
        if not api_key or not model:
            raise ValueError("model and API key are required")
        ok, msg = validate_key(base_url, model, api_key)
        if not ok:
            raise ValueError(f"key validation failed: {msg}")
        kid = uuid.uuid4().hex[:12]
        item = {"customer_id": cid, "sk": f"key#{kid}", "key_id": kid, "provider": provider,
                "base_url": base_url, "model": model, "ciphertext": self.vault.encrypt(api_key, cid, kid),
                "price_in_per_m": str(price_in_per_m), "price_out_per_m": str(price_out_per_m),
                "added_at": now(), "validated_at": now()}
        self.table.put_item(Item=item)
        return self._public_key(item)

    @staticmethod
    def _public_key(it: dict) -> dict:
        return {k: it[k] for k in ("key_id", "provider", "base_url", "model", "added_at", "validated_at")} | {
            "price_in_per_m": float(it["price_in_per_m"]), "price_out_per_m": float(it["price_out_per_m"])}

    def _items(self, cid: str, prefix: str) -> list[dict]:
        r = self.table.query(KeyConditionExpression=Key("customer_id").eq(cid) & Key("sk").begins_with(prefix))
        return r["Items"]

    def list_keys(self, cid: str) -> list[dict]:
        return [self._public_key(it) for it in self._items(cid, "key#")]

    def revoke_key(self, cid: str, kid: str) -> None:
        self.table.delete_item(Key={"customer_id": cid, "sk": f"key#{kid}"})

    def key_secret(self, cid: str, kid: str) -> dict:
        """Worker-side only: decrypted key + endpoint. Never send this to a browser or a log."""
        it = self.table.get_item(Key={"customer_id": cid, "sk": f"key#{kid}"}).get("Item")
        if not it:
            raise KeyError("key not found or revoked")
        return self._public_key(it) | {"api_key": self.vault.decrypt(it["ciphertext"], cid, kid)}

    # ---- run counter + usage log --------------------------------------------------------------
    def usage_log(self, cid: str, mon: str | None = None) -> list[dict]:
        items = self._items(cid, f"usage#{mon}#" if mon else "usage#")
        return sorted(({k: v for k, v in it.items() if k not in ("customer_id", "sk")} for it in items),
                      key=lambda u: u.get("started_at", ""))

    def runs_used(self, cid: str, mon: str | None = None) -> int:
        return sum(1 for u in self.usage_log(cid, mon or month()) if u.get("counted"))

    def quote_next_run(self, cid: str) -> dict:
        plan = PLANS[self.profile(cid)["plan"]]
        used = self.runs_used(cid)
        extra = used >= plan["included_runs"]
        return {"plan": plan["name"], "used": used, "included": plan["included_runs"], "next_is_extra": extra,
                "extra_run_usd": EXTRA_RUN_USD if extra else 0.0}

    def start_run(self, cid: str, run_id: str, *, key_id: str, task: str, max_usd: float, extra: bool) -> None:
        self.table.put_item(Item={"customer_id": cid, "sk": f"usage#{month()}#{run_id}", "run_id": run_id,
                                  "task": task, "key_id": key_id, "max_usd": str(max_usd),
                                  "started_at": now(), "status": "running", "counted": False,
                                  "extra_run": extra, "overage_usd": "0", "payment_status": "n/a"})

    def finish_run(self, cid: str, run_id: str, started_month: str, *, stopped: str, round_done: int,
                   ours: dict, theirs: dict) -> dict:
        it = self.table.get_item(Key={"customer_id": cid, "sk": f"usage#{started_month}#{run_id}"}).get("Item") or {}
        counted = counts_as_run(stopped, round_done)
        overage = EXTRA_RUN_USD if counted and it.get("extra_run") else 0.0
        upd = {"status": stopped, "rounds_done": round_done, "counted": counted, "finished_at": now(),
               "optimizer_tokens": ours.get("prompt_tokens", 0) + ours.get("completion_tokens", 0),
               "optimizer_usd": f"{ours.get('usd', 0):.6f}",
               "scoring_tokens_est": theirs.get("prompt_tokens", 0) + theirs.get("completion_tokens", 0),
               "scoring_usd_est": f"{theirs.get('usd', 0):.6f}",
               "overage_usd": f"{overage:.2f}", "payment_status": "pending" if overage else "n/a"}
        self.table.update_item(
            Key={"customer_id": cid, "sk": f"usage#{started_month}#{run_id}"},
            UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in upd),
            ExpressionAttributeNames={f"#{k}": k for k in upd},
            ExpressionAttributeValues={f":{k}": v for k, v in upd.items()})
        return upd


def estimate_run(adapter, rounds: int, price_in_per_m: float, price_out_per_m: float,
                 tokens_per_example: float | None = None) -> dict:
    """Scoring calls x tokens x price, all on the customer's key. Approximate by design."""
    from .split import Split  # noqa: F401  (documentation: sizes come from the frozen split)
    from .tasks import load_or_create_split
    split, _ = load_or_create_split(adapter.name, adapter)
    tr, va, ho = len(split.train_ids), len(split.val_ids), len(split.heldout_ids)
    batch = min(adapter.train_minibatch or tr, tr)
    per_round = adapter.proposals_per_round * batch + (batch if adapter.train_minibatch else 0) + 3 * va
    calls = (tr + va) + rounds * per_round + 2 * ho * adapter.heldout_repeats
    tpe = tokens_per_example or getattr(adapter, "est_tokens_per_example", 500)
    tokens = calls * tpe
    usd = tokens * (0.85 * price_in_per_m + 0.15 * price_out_per_m) / 1e6
    return {"scoring_calls": calls, "tokens_per_call": tpe, "scoring_tokens": int(tokens),
            "scoring_usd": round(usd, 4), "formula": f"{calls} calls (examples x candidates x rounds, plus "
            f"baseline + held-out) x ~{tpe:.0f} tokens x provider price"}
