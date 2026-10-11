"""AWS App Monetization runtime calls (HTTP-direct integration; no SDK for Python).

Three SigV4-signed calls, all carrying the same scope (sandbox or live) derived from MONETIZATION_APP_ID:
  - check_entitlement(): GetEntitlementDecision, called before a run starts. FAILS CLOSED: anything other
    than an explicit "ALLOW" (DENY, non-2xx, timeout, parse error) is treated as deny.
  - put_event():         PutEvent for one counted optimization run, keyed by run_id (idempotent).
  - checkout_session() / billing_portal(): mint hosted pricing/checkout and billing-portal URLs (no UI code).
Connection comes from .env.monetization (MONETIZATION_ENDPOINT, MONETIZATION_REGION, MONETIZATION_APP_ID).
The caller's AWS credentials (the app's execution role, or the developer's locally) sign the requests.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

import botocore.session
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from dotenv import dotenv_values

EVENT_TYPE = "optimization_run"
SERVICE = "appmonetization"


class BillingError(Exception):
    pass


def _conf() -> dict:
    vals = dict(dotenv_values(Path(".env.monetization"))) if Path(".env.monetization").exists() else {}
    vals.update({k: v for k, v in os.environ.items() if k.startswith("MONETIZATION_")})
    return vals


def _identity() -> tuple[str, str, str]:
    """(endpoint, bare appId, scope). scope = sandbox iff MONETIZATION_APP_ID is a /sandbox ARN."""
    c = _conf()
    raw = (c.get("MONETIZATION_APP_ID") or "").strip()
    endpoint = (c.get("MONETIZATION_ENDPOINT") or "").rstrip("/")
    if not raw or not endpoint:
        raise BillingError("billing not configured (MONETIZATION_APP_ID / MONETIZATION_ENDPOINT)")
    scope = "sandbox" if raw.endswith("/sandbox") else "live"
    app_id = raw.removesuffix("/sandbox")
    for marker in ("apps/", "app/"):
        if marker in app_id:
            app_id = app_id.split(marker, 1)[1]
    return endpoint, app_id, scope


def _region(endpoint: str) -> str:
    return _conf().get("MONETIZATION_REGION") or endpoint.split("//", 1)[1].split(".")[0]


def _signed(method: str, path: str, query: dict, body: dict | None = None, timeout: float = 10.0) -> httpx.Response:
    endpoint, _, _ = _identity()
    url = f"{endpoint}{path}?{urlencode(query)}"
    data = json.dumps(body) if body is not None else None
    req = AWSRequest(method=method, url=url, data=data,
                     headers={"Content-Type": "application/json"} if data else {})
    creds = botocore.session.get_session().get_credentials()
    if creds is None:
        raise BillingError("no AWS credentials available to sign billing calls")
    SigV4Auth(creds.get_frozen_credentials(), SERVICE, _region(endpoint)).add_auth(req)
    return httpx.request(method, url, content=data, headers=dict(req.headers.items()), timeout=timeout)


def check_entitlement(user_id: str, event_type: str = EVENT_TYPE) -> dict:
    """Returns {"allowed": bool, "reason": str|None, "planId": ..., "suggestedPlanId": ...}. Fail closed."""
    try:
        _, app_id, scope = _identity()
        r = _signed("GET", f"/apps/{app_id}/entitlements/check",
                    {"userId": user_id, "eventType": event_type, "scope": scope})
        d = r.json() if r.status_code // 100 == 2 else {}
        allowed = r.status_code // 100 == 2 and d.get("decision") == "ALLOW"
        return {"allowed": allowed, "reason": d.get("reason") or (None if allowed else f"HTTP {r.status_code}"),
                "planId": d.get("planId"), "suggestedPlanId": d.get("suggestedPlanId")}
    except Exception as e:  # noqa: BLE001 - fail closed on anything unexpected
        return {"allowed": False, "reason": f"entitlement check failed ({type(e).__name__})"}


def put_event(user_id: str, run_id: str, event_type: str = EVENT_TYPE, quantity: str = "1",
              properties: dict | None = None) -> bool:
    """One metered event per counted run. clientToken = run_id makes retries idempotent."""
    _, app_id, scope = _identity()
    body = {"userId": user_id, "eventType": event_type, "quantity": quantity, "clientToken": run_id[:64],
            "timestamp": round(datetime.now(timezone.utc).timestamp(), 3),   # epoch seconds on the wire
            "properties": properties or {"run_id": run_id}}
    r = _signed("POST", f"/apps/{app_id}/events", {"scope": scope}, body)
    if r.status_code // 100 != 2:
        raise BillingError(f"PutEvent failed: HTTP {r.status_code}")
    return True


def checkout_session(user_id: str, return_url: str, plan_id: str | None = None) -> dict:
    """plan_id omitted -> hosted pricing page. Returns {"redirect": url|None, "kind": ..., "effectiveAt": ...}."""
    _, app_id, scope = _identity()
    body = {"returnUrl": return_url, "refreshUrl": return_url, "clientToken": uuid.uuid4().hex}
    if plan_id:
        body["planId"] = plan_id
    r = _signed("POST", f"/apps/{app_id}/users/{quote(user_id, safe='')}/checkout-sessions", {"scope": scope}, body)
    if r.status_code // 100 != 2:
        raise BillingError(f"checkout session failed: HTTP {r.status_code}")
    o = r.json().get("outcome", {})
    if "paymentRequired" in o:
        return {"kind": "paymentRequired", "redirect": o["paymentRequired"].get("checkoutUrl")}
    if "planSelectionRequired" in o:
        return {"kind": "planSelectionRequired", "redirect": o["planSelectionRequired"].get("pricingUrl")}
    if "paymentNotRequired" in o:
        return {"kind": "paymentNotRequired", "redirect": None,
                "effectiveAt": o["paymentNotRequired"].get("effectiveAt")}
    raise BillingError("unexpected checkout outcome")


def billing_portal(user_id: str, return_url: str) -> str:
    _, app_id, scope = _identity()
    r = _signed("POST", f"/apps/{app_id}/users/{quote(user_id, safe='')}/billing-portal-sessions", {"scope": scope},
                {"returnUrl": return_url, "refreshUrl": return_url, "clientToken": uuid.uuid4().hex})
    if r.status_code // 100 != 2:
        raise BillingError(f"billing portal failed: HTTP {r.status_code}")
    return r.json()["billingPortalUrl"]
