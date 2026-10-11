"""Record the automated segments of the demo walkthrough (no login needed) with Playwright.

Usage: python scripts/record_demo.py   (dashboard must be running at http://localhost:8000)
Writes webm clips to video/clips/. Stitch with scripts/stitch_demo.py.
"""
from __future__ import annotations

import shutil
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://localhost:8000/"
RUN = "banking77-20261011-142259"
OUT = Path("video/clips")
W, H = 1280, 720

CARD = """<!doctype html><meta charset=utf-8><style>
body{margin:0;height:100vh;display:grid;place-items:center;background:#12110f;color:#f2efe9;font:600 22px system-ui,Segoe UI,sans-serif}
.k{color:#f59e0b;font-size:16px;letter-spacing:.14em;text-transform:uppercase;margin-bottom:14px}
h1{margin:0;font-size:54px;letter-spacing:-.02em} h1 span{color:#f59e0b} p{color:#a29d94;font-weight:400;margin:14px 0 0}
</style><div style="text-align:center"><div class=k>{kicker}</div><h1>{title}</h1><p>{sub}</p></div>"""

LIST = """<!doctype html><meta charset=utf-8><style>
body{margin:0;height:100vh;display:grid;place-items:center;background:#12110f;color:#f2efe9;font:400 21px system-ui,Segoe UI,sans-serif}
.w{width:1060px}.k{color:#f59e0b;font:600 16px system-ui;letter-spacing:.14em;text-transform:uppercase;margin-bottom:10px}
h1{margin:0 0 22px;font-size:42px;letter-spacing:-.02em}ul{margin:0;padding:0;list-style:none}
li{padding:11px 0;border-top:1px solid #2f2d29}li b{color:#f59e0b;font-weight:700}
</style><div class=w><div class=k>{kicker}</div><h1>{title}</h1><ul>{items}</ul></div>"""

# Update when replies come in (shown in the video's "Selling it" segment).
SALES = [
    "<b>Prospect 1</b>: CEO of my employer (disclosed), a government contractor building AI developer tools. "
    "Pilot on their AI code-fixing pipeline: <b>-23% tokens/run</b>, same fix rate",
    "<b>Reply</b>: \"That sounds exciting\". Referred us to their technical lead to evaluate. Offer sent",
    "<b>Prospect 2</b>: an executive at a second company with AI prompts in production. Offer sent, awaiting reply",
    "<b>Offer</b>: Founding plan $49/mo locked 12 months, 4 runs, $5 per extra run, scoring on their own AI key",
]
AWS = [
    "<b>App Monetization</b> (private beta): 2 subscription plans + <b>$5 metered extra runs</b>, fail-closed entitlement before every run",
    "<b>Cognito</b> sign-up/sign-in · <b>KMS</b>-encrypted customer API keys (bound to customer + key id)",
    "<b>DynamoDB</b> run history, accounts, usage log · <b>Lambda + ECR</b> public dashboard",
    "<b>IAM</b> least privilege: the public site can only read run history",
]

CAPTION_JS = """(t) => { let c = document.getElementById('__cap'); if (!c) { c = document.createElement('div'); c.id='__cap';
 c.style.cssText='position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:99999;background:rgba(18,17,15,.88);color:#fff;'
 +'font:600 20px system-ui,Segoe UI,sans-serif;padding:10px 18px;border-radius:12px;border:1px solid #f59e0b;max-width:86%;text-align:center';
 document.body.appendChild(c);} c.textContent = t; }"""


def clip(browser, name: str, fn) -> None:
    ctx = browser.new_context(viewport={"width": W, "height": H}, record_video_dir=str(OUT / "_tmp"),
                              record_video_size={"width": W, "height": H}, color_scheme="dark")
    page = ctx.new_page()
    fn(page)
    page.close()
    vid = Path(page.video.path())
    ctx.close()
    shutil.move(str(vid), OUT / f"{name}.webm")
    print("recorded", name)


def card(kicker: str, title: str, sub: str = "", secs: float = 2.5):
    def fn(page):
        page.set_content(CARD.replace("{kicker}", kicker).replace("{title}", title).replace("{sub}", sub))
        page.wait_for_timeout(int(secs * 1000))
    return fn


def list_card(kicker: str, title: str, items: list[str], secs: float):
    def fn(page):
        page.set_content(LIST.replace("{kicker}", kicker).replace("{title}", title)
                         .replace("{items}", "".join(f"<li>{i}</li>" for i in items)))
        page.wait_for_timeout(int(secs * 1000))
    return fn


def cap(page, text: str, ms: int) -> None:
    page.evaluate(CAPTION_JS, text)
    page.wait_for_timeout(ms)


def smooth_scroll(page, y: int, ms: int = 900) -> None:
    page.evaluate(f"window.scrollTo({{top:{y},behavior:'smooth'}})")
    page.wait_for_timeout(ms)


def signup(page) -> None:
    """Our sign-up portal (Amazon Cognito). Placeholder values; nothing is submitted."""
    page.goto(BASE)
    page.wait_for_selector("#tabs")
    page.evaluate("try{sessionStorage.clear()}catch(e){}")
    page.click('[data-view="account"]')
    page.wait_for_selector("#go-signup")
    page.click("#go-signup")
    cap(page, "Step 1: customers create an account (Amazon Cognito, passwords never touch our servers' storage)", 1800)
    page.type("#s-email", "you@company.com", delay=45)
    page.type("#s-pass", "demo-password-1", delay=25)
    page.type("#s-pass2", "demo-password-1", delay=25)
    cap(page, "Email + password (10+ chars), then Cognito emails a 6-digit verification code", 2200)
    page.evaluate("loginView('confirm', 'you@company.com')")
    page.type("#c-code", "482913", delay=90)
    cap(page, "Verify the code and you're signed in. The account's Cognito ID becomes its billing identity", 2600)


def aws_pricing(page) -> None:
    u = json.loads(Path(".monetize/video-urls.json").read_text())
    page.goto(u["pricing"], wait_until="networkidle", timeout=45000)
    page.wait_for_timeout(600)
    cap(page, "Step 2: AWS App Monetization's hosted pricing page (sandbox), no billing UI code on our side", 2500)
    page.hover("text=Choose plan >> nth=0")
    cap(page, "Founding customer: $49/mo, 4 optimization runs, $5 per extra run, price locked 12 months", 2600)


def aws_checkout(page) -> None:
    u = json.loads(Path(".monetize/video-urls.json").read_text())
    page.goto(u["checkout"], wait_until="networkidle", timeout=45000)
    page.wait_for_timeout(600)
    cap(page, "AWS-hosted checkout: billing address, then card. Invoice preview: $49.00, tax calculated by AWS", 3200)
    page.hover("text=Invoice preview")
    cap(page, "Sandbox mode: test cards only, no real charges", 2200)


def results(page) -> None:
    page.goto(BASE + "#" + RUN)
    page.wait_for_selector(".hero .big", timeout=20000)
    page.wait_for_timeout(800)
    cap(page, "Held-out proof: 400 official test examples it never saw. 72.0% → 81.5% (95% CI +5.5 to +13.5 pts)", 4000)
    smooth_scroll(page, 330)
    cap(page, "8 rounds × 4 agents in parallel (mutate, crossover, fresh). Best prompt: 70% → 85% on validation", 4600)
    smooth_scroll(page, 780)
    cap(page, "Every proposal is scored on the same fresh batch as the champion, then kept or discarded", 2400)
    first = page.locator(".cand").nth(1)
    first.click()
    page.wait_for_timeout(300)
    cap(page, "Click any proposal to read the exact prompt it tried", 2200)
    first.click()
    page.locator("text=Lessons from the analyst agent").scroll_into_view_if_needed()
    page.wait_for_timeout(500)
    cap(page, "An analyst agent turns failures into lessons that steer the next round's proposals", 3200)
    page.locator("text=How the prompt evolved").scroll_into_view_if_needed()
    page.evaluate("window.scrollBy({top:260,behavior:'smooth'})")
    page.wait_for_timeout(700)
    cap(page, "What it learned, as a diff (green = added). Whole run: $0.87, 34% fewer errors", 3600)


def pricing(page) -> None:
    page.goto(BASE)
    page.wait_for_selector("#tabs")
    page.click('[data-view="pricing"]')
    page.wait_for_timeout(600)
    cap(page, "Plans: Founding $49/mo (4 runs) or Standard $199/mo (10), extra runs $5. Scoring tokens bill to YOUR AI key", 4200)


def main() -> None:
    import sys
    only = set(sys.argv[1:])            # e.g. `python scripts/record_demo.py 06c_sales` re-records one segment
    OUT.mkdir(parents=True, exist_ok=True)
    global clip
    _clip = clip
    clip = (lambda b, name, fn: _clip(b, name, fn) if not only or name in only else None)
    with sync_playwright() as p:
        b = p.chromium.launch()
        clip(b, "00_intro", card("Hackathon demo", "Whet<span>stone</span>",
                                 "A self-improving prompt optimizer that proves its gains on unseen tests", 3.0))
        clip(b, "01_card_account", card("Step 1", "Create your account", "Amazon Cognito sign-up with email verification", 2.0))
        clip(b, "01b_signup", signup)
        clip(b, "02_card_plan", card("Step 2", "Choose a plan &amp; pay", "AWS App Monetization: hosted pricing + checkout (sandbox)", 2.0))
        clip(b, "03_pricing", pricing)
        clip(b, "03b_aws_pricing", aws_pricing)
        clip(b, "03c_aws_checkout", aws_checkout)
        clip(b, "04_card_run", card("Step 3", "Run an optimization", "Bring your AI key (encrypted with AWS KMS), see the cost estimate, confirm", 2.0))
        clip(b, "05_card_results", card("Step 4", "See the results", "Every round, every agent, every prompt", 2.0))
        clip(b, "06_results", results)
        clip(b, "06b_aws", list_card("Under the hood", "Built on AWS", AWS, 5.0))
        clip(b, "06c_sales", list_card("Build and sell", "Selling it today", SALES, 6.5))
        clip(b, "07_outro", card("Results", "72% → 81.5% <span>·</span> −23% tokens",
                                 "Held-out accuracy (Banking77, 400 unseen) · −23% tokens on a government contractor's AI code-fixing tool, same fix rate", 4.0))
        b.close()
    shutil.rmtree(OUT / "_tmp", ignore_errors=True)


if __name__ == "__main__":
    main()
