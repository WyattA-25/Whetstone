# Whetstone: Progress

Handoff file. If Claude usage runs out, Codex or a human picks up from here.
The full spec is `claude_code_kickoff_prompt.md`; the approved plan is summarized below.

## Approved plan (Phase 2)

| # | Step | Status |
|---|---|---|
| 1 | Repo & environment | ✅ done |
| 2 | Core library (Luminal client, TaskAdapter interface, objective, frozen split + hash, storage) | ✅ done |
| 3 | Adapter A: text classification (exact match) | ✅ done |
| 4 | Optimizer loop (mutate / crossover / fresh / analyst, selection, budgets, resumable) | ✅ built; first full run in progress |
| 5 | Code-fix data (teammate): repos → SARIF findings → frozen split | 🟡 collector done (`scripts/collect_findings.py`); waiting on Chayce's `data/codefix/repos.yaml` |
| 6 | Adapter B: code-fix (sandbox, Luminal fixer, re-scan + tests, cache) | ✅ done (verifier self-test passes; dev baseline 6/8 on itsdangerous) |
| ✂ | Cut line 3:00 PM | |
| 7 | Persistence → **DynamoDB** (option A; replaces Atlas) | ⏭ next (needs AWS CLI configured) |
| 8 | Unattended code-fix run + held-out evaluation | |
| 9 | Employer pilot (only if approved; private config, never committed) | |
| 10 | Results UI (FastAPI + HTML) | |
| ✂ | Cut line 5:00 PM | |
| 11 | Customer features (BYO key, cost estimate, spend limit, run counter, usage log) | |
| 12a | Payments (AWS beta tool; Stripe test-mode fallback) | |
| 12b | Deploy (ECR → App Runner, KMS) | |
| ✂ | Cut line 7:00 PM: features stop | |
| 13 | Sale message draft | |
| 14 | Demo video script | |
| 15 | README + submission | |

## Prize targets (decided)

- **T1 Transpose / Luminal** ($3k): core loop + held-out result. Highest priority.
- **T2 Build AND Sell**: both the **Sales prize** (employer founding-customer sale) and the **AWS prize**.
- MongoDB: not entered. Step 7 persistence = **AWS DynamoDB** (counts toward the AWS prize). Chayce: skip Atlas.
- Priority if behind: T1 > Sales > AWS.

## Team

- Wyatt (WyattA-25): lead, reviews and runs everything.
- Chayce (Chayce-Allison): GitHub repo setup, Atlas/AWS accounts, findings data + split, testing, video recording.

## Repo

https://github.com/WyattA-25/Whetstone (private until step 15). Commits use the GitHub noreply email.

## Key decisions

- Optimization objective is configurable (success rate, tokens, time, cost, with constraints).
- Code-fix adapter accepts any scanner that outputs SARIF; parsers for others.
- Fixer inside the loop = Luminal flash model.
- UI = FastAPI + single HTML page. Deploy = App Runner (web); optimization worker runs separately.

## Current numbers

- Luminal: `https://flash.luminal.cloud/v1`, only model `deepseek-ai/DeepSeek-V4.1-Flash`.
  Reasoning model (hidden reasoning tokens count as completion tokens). ~0.7-1.5s per short call.
- Rate limit: ~10 concurrent requests OK, more get HTTP 429. Default concurrency 8 + exponential backoff.
- **Classify baseline** (Banking77, 10 confusable intents, 200 examples; split 100/40/60,
  held-out hash `98b8b9b1...185e7b`): train **66%**, val **75%**, ~320 tok/ex, 0 errors.
  Run: `python -m whetstone.baseline --task classify`.
- **Noise:** same prompt at temperature 0 gave val 70% / 80% / 75% across runs. The model is
  nondeterministic, so selection must re-check winners and report confidence intervals.
- Prices in `.env` are placeholder estimates ($0.10 in / $0.40 out per 1M); replace with Luminal's real price.

## Code-fix adapter notes

- Dev data: `python scripts/collect_findings.py --repos data/codefix/repos.example.yaml --out data/codefix/dev/findings.jsonl`
- Verifier self-test: `python -m whetstone.tasks.codefix --selftest --findings data/codefix/dev/findings.jsonl --repos data/codefix/repos.example.yaml`
  (no-op fails, noqa rejected, breaking change fails tests, tests import the sandbox copy, original untouched)
- Dev baseline (itsdangerous, 8 scored): 6/8 fixed, ~3.3k tok/ex, ~6s LLM + ~2.4s verify per attempt.
  Both failures were security findings (S324, S110) "fixed" with a suppression comment -> rejected.
- Memory cap applies on Linux/macOS only (no setrlimit on Windows); timeouts apply everywhere.
- Real data: Chayce's `data/codefix/repos.yaml` -> `python scripts/collect_findings.py` -> `data/codefix/findings.jsonl`;
  the split freezes on the first `python -m whetstone.baseline --task codefix`.

## Known issues

- Luminal intermittently returns 503 "model temporarily unavailable" / connection errors (seen 12:49-13:06).
  Loop tolerates it: failed agents skipped, failed rounds retried with backoff, everything resumable.
- Agent replies with thinking ON sometimes spent all 4096 tokens reasoning and returned nothing.
  Fix: agents run with `extra_body={"thinking": {"type": "disabled"}}` (set `LUMINAL_AGENT_THINKING=on` to revert).
  Scoring calls keep the provider default (reasoning on) so baselines stay comparable.
- Check a run from any shell: `python -m whetstone.status` (add `--all` for the full log).
- Don't run baseline/manual scripts while a run is going: they share the ~10-concurrent rate limit.

## Open questions

- Luminal real per-token price (for cost estimates).
- AWS "best use" criteria; judging rubric.
- Employer: pilot permission, harness request/response format (ports 8080 / 5050), model used.

## Confidentiality

- Employer identifiers go in `configs/private/denylist.txt` (git-ignored, one term per line).
- The pre-commit hook (`.githooks/pre-commit`) blocks pilot paths, `.env`, denylisted terms, and obvious secrets.
