"""Whetstone web UI. Run locally: python -m whetstone.web  (then open http://127.0.0.1:8000).

Account endpoints (API keys, starting runs) are OFF unless WHETSTONE_ACCOUNT_API=on, so the public deployment
is a read-only dashboard + pricing page. For the hackathon demo there is a single customer, "demo".
"""
from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

load_dotenv()

from ..accounts import DEMO_CUSTOMER, EXTRA_RUN_USD, PLANS  # noqa: E402
from .data import RunReader  # noqa: E402  (reads env set by load_dotenv)

STATIC = Path(__file__).parent / "static"
ROOT = Path(__file__).resolve().parents[2]
ACCOUNT_API = os.getenv("WHETSTONE_ACCOUNT_API", "off") == "on"
TASKS = {"banking77": "Support-ticket intent classification (Banking77)",
         "codefix": "Fix static-analysis findings in real repos"}

app = FastAPI(title="Whetstone", docs_url=None, redoc_url=None)
reader = RunReader()
_accounts = None


def accounts():
    global _accounts
    if not ACCOUNT_API:
        raise HTTPException(403, "account features are disabled on this deployment")
    if _accounts is None:
        from ..accounts import Accounts
        _accounts = Accounts()
    return _accounts


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "source": reader.source}


@app.get("/api/config")
def config() -> dict:
    return {"account_api": ACCOUNT_API, "plans": PLANS, "extra_run_usd": EXTRA_RUN_USD, "tasks": TASKS}


@app.get("/api/runs")
def runs() -> list[dict]:
    return reader.list_runs()


@app.get("/api/runs/{run_id}")
def run(run_id: str) -> dict:
    data = reader.get_run(run_id)
    if data is None:
        raise HTTPException(404, "run not found")
    return data


# ---- account (local demo only) ----------------------------------------------------------------
class PlanIn(BaseModel):
    plan: str


class KeyIn(BaseModel):
    provider: str = Field(max_length=40)
    base_url: str = Field(default="", max_length=300)
    model: str = Field(max_length=120)
    api_key: str = Field(max_length=500)
    price_in_per_m: float = Field(default=0.10, ge=0, le=1000)
    price_out_per_m: float = Field(default=0.40, ge=0, le=1000)


class RunIn(BaseModel):
    task: str
    rounds: int = Field(default=6, ge=1, le=20)
    key_id: str
    max_usd: float = Field(gt=0, le=1000, description="customer's spending limit on their own key, per run")
    confirm_cost: bool = False
    confirm_extra: bool = False


@app.get("/api/account")
def account() -> dict:
    a = accounts()
    prof = a.profile(DEMO_CUSTOMER)
    return {"profile": prof, "plan": PLANS[prof["plan"]], "quote": a.quote_next_run(DEMO_CUSTOMER),
            "keys": a.list_keys(DEMO_CUSTOMER), "usage": a.usage_log(DEMO_CUSTOMER)}


@app.post("/api/account/plan")
def set_plan(body: PlanIn) -> dict:
    try:
        return accounts().set_plan(DEMO_CUSTOMER, body.plan)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@app.post("/api/account/keys")
def add_key(body: KeyIn) -> dict:
    try:  # the key is validated, encrypted with KMS, and never echoed back
        return accounts().add_key(DEMO_CUSTOMER, provider=body.provider, base_url=body.base_url, model=body.model,
                                  api_key=body.api_key, price_in_per_m=body.price_in_per_m,
                                  price_out_per_m=body.price_out_per_m)
    except ValueError as e:
        raise HTTPException(400, str(e)) from None


@app.delete("/api/account/keys/{key_id}")
def revoke_key(key_id: str) -> dict:
    accounts().revoke_key(DEMO_CUSTOMER, key_id)
    return {"revoked": key_id}


def _estimate(body: RunIn) -> dict:
    from ..accounts import estimate_run
    from ..tasks import get_task
    if body.task not in TASKS:
        raise HTTPException(400, "unknown task")
    a = accounts()
    key = next((k for k in a.list_keys(DEMO_CUSTOMER) if k["key_id"] == body.key_id), None)
    if not key:
        raise HTTPException(400, "choose one of your API keys")
    est = estimate_run(get_task(body.task), body.rounds, key["price_in_per_m"], key["price_out_per_m"])
    quote = a.quote_next_run(DEMO_CUSTOMER)
    return {"estimate": est, "quote": quote, "key": key, "spending_limit_usd": body.max_usd,
            "limit_may_stop_early": est["scoring_usd"] > body.max_usd}


@app.post("/api/account/estimate")
def estimate(body: RunIn) -> dict:
    return _estimate(body)


@app.post("/api/account/runs")
def start_run(body: RunIn) -> dict:
    info = _estimate(body)
    if not body.confirm_cost:
        raise HTTPException(400, "confirm the cost estimate first")
    if info["quote"]["next_is_extra"] and not body.confirm_extra:
        raise HTTPException(402, f"all included runs used: confirm the ${EXTRA_RUN_USD:.0f} extra-run charge")
    if any(u.get("status") == "running" for u in accounts().usage_log(DEMO_CUSTOMER)):
        raise HTTPException(409, "a run is already in progress")
    run_id = f"{body.task}-{datetime.now():%Y%m%d-%H%M%S}"
    cmd = [sys.executable, "-m", "whetstone.run", "--task", body.task, "--rounds", str(body.rounds),
           "--max-usd-scoring", str(body.max_usd), "--customer", DEMO_CUSTOMER, "--key-id", body.key_id,
           "--run-id", run_id] + (["--confirm-extra"] if body.confirm_extra else [])
    log = (ROOT / "runs" / f"{run_id}.worker.log")
    log.parent.mkdir(exist_ok=True)
    subprocess.Popen(cmd, cwd=ROOT, stdout=log.open("w"), stderr=subprocess.STDOUT)  # the key is fetched by the worker
    return {"run_id": run_id, "extra_run": info["quote"]["next_is_extra"]}
