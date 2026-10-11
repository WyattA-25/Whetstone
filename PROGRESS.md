# Linguist: Progress

Handoff file. If Claude usage runs out, Codex or a human picks up from here.
The full spec is `claude_code_kickoff_prompt.md`; the approved plan is summarized below.

## Approved plan (Phase 2)

| # | Step | Status |
|---|---|---|
| 1 | Repo & environment | ✅ done |
| 2 | Core library (Luminal client, TaskAdapter interface, objective, frozen split + hash, storage) | ⏭ next |
| 3 | Adapter A: text classification (exact match) | |
| 4 | Optimizer loop (mutate / crossover / fresh / analyst, selection, budgets, resumable) | |
| 5 | Code-fix data (teammate): repos → SARIF findings → frozen split | |
| 6 | Adapter B: code-fix (sandbox, Luminal fixer, re-scan + tests, cache) | |
| ✂ | Cut line 3:00 PM | |
| 7 | MongoDB Atlas persistence | |
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

## Team

- Wyatt (WyattA-25): lead, reviews and runs everything.
- Chayce (Chayce-Allison): GitHub repo setup, Atlas/AWS accounts, findings data + split, testing, video recording.

## Key decisions

- Optimization objective is configurable (success rate, tokens, time, cost, with constraints).
- Code-fix adapter accepts any scanner that outputs SARIF; parsers for others.
- Fixer inside the loop = Luminal flash model.
- UI = FastAPI + single HTML page. Deploy = App Runner (web); optimization worker runs separately.

## Current numbers

None yet.

## Open questions

- Luminal: exact model names, base URL, rate limits (needed for step 2).
- AWS "best use" criteria; judging rubric.
- Employer: pilot permission, harness request/response format (ports 8080 / 5050), model used.
- Git commit email is currently a personal Gmail; confirm before the repo goes public.

## Confidentiality

- Employer identifiers go in `configs/private/denylist.txt` (git-ignored, one term per line).
- The pre-commit hook (`.githooks/pre-commit`) blocks pilot paths, `.env`, denylisted terms, and obvious secrets.
