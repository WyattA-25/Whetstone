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
| 5 | Code-fix data: repos → findings → frozen split | ✅ 110 findings, 5 repos (itsdangerous, boltons, prettytable, tabulate, click), 39 rules; split freezes on first codefix baseline |
| 6 | Adapter B: code-fix (sandbox, Luminal fixer, re-scan + tests, cache) | ✅ done (verifier self-test passes; dev baseline 6/8 on itsdangerous) |
| ✂ | Cut line 3:00 PM | |
| 7 | Persistence → **DynamoDB** (option A; replaces Atlas) | ✅ done |
| 8 | Unattended code-fix run + held-out evaluation | 🟡 eval tool done (`python -m whetstone.final_eval <run_id>`); classify redesign pending decision |
| 9 | Employer pilot (only if approved; private config, never committed) | |
| 10 | Results UI (FastAPI + HTML) | ✅ done: `python -m whetstone.web` → http://127.0.0.1:8000 |
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

## AWS

- Account 079755088097, IAM user `Whetstone-dev`, region us-east-1. CLI: `C:\Program Files\Amazon\AWSCLIV2ws.exe`.
- DynamoDB (on-demand): `whetstone-runs` (run_id + sk) and `whetstone-accounts` (customer_id + sk).
  Create/verify: `python -m whetstone.aws_setup`. With `WHETSTONE_STORE=dynamo`, runs write locally AND to DynamoDB.
  Backfill/repair: `python -m whetstone.sync <run_id>` or `--all` (idempotent).
- Sandboxed code gets no AWS env vars and AWS_SHARED_CREDENTIALS_FILE/AWS_CONFIG_FILE point at devnull.
  It is still a same-user process (not OS-isolated) — a container sandbox is the production answer.

## Code-fix adapter notes

- Dev data: `python scripts/collect_findings.py --repos data/codefix/repos.example.yaml --out data/codefix/dev/findings.jsonl`
- Verifier self-test: `python -m whetstone.tasks.codefix --selftest --findings data/codefix/dev/findings.jsonl --repos data/codefix/repos.example.yaml`
  (no-op fails, noqa rejected, breaking change fails tests, tests import the sandbox copy, original untouched)
- Dev baseline (itsdangerous, 8 scored): 6/8 fixed, ~3.3k tok/ex, ~6s LLM + ~2.4s verify per attempt.
  Both failures were security findings (S324, S110) "fixed" with a suppression comment -> rejected.
- Memory cap applies on Linux/macOS only (no setrlimit on Windows); timeouts apply everywhere.
- Real data: Chayce's `data/codefix/repos.yaml` -> `python scripts/collect_findings.py` -> `data/codefix/findings.jsonl`;
  the split freezes on the first `python -m whetstone.baseline --task codefix`.

## Headline experiment: task `banking77` (classify v2)

- Data: train 120 / val 80 from Banking77's official train file; held-out = all 400 official test examples
  for the 10 intents (6 train/test duplicate texts excluded). Split is predefined and hash-frozen.
- Scoring with model thinking OFF (`scoring_extra_body`), like a production classifier.
- Each round: 4 proposers; candidates + champion scored on a fresh seeded 60-example train sample (paired);
  top-2 + champion checked on val; promotion = beats champion's running-mean val score.
- Run: `python -m whetstone.run --task banking77 --rounds 8`; final: `python -m whetstone.final_eval <run_id>`
  (1 repeat by default for this task: 400 examples x 2 prompts = 800 calls).
- Old task `classify` (v1) is kept for the record but retired.

## Web UI

- `python -m whetstone.web` (or the `whetstone-ui` preview config). Reads DynamoDB when WHETSTONE_STORE=dynamo,
  else local `runs/`. Override with WHETSTONE_UI_SOURCE=local|dynamo.
- Shows held-out result (or "pending"), validation baseline→best, rounds, spend split ours/customer,
  score-per-round chart (best line + every proposal as a dot), agent feed (click to expand prompts),
  analyst lessons, and a word-level prompt diff across the champion lineage. Auto-refreshes live runs.
- Private runs (state.private or task "pilot*") are never served.

## Findings so far (be honest in README/video)

- Classify v1 (reasoning ON for scoring, 100/40/60 split): train rose 66% -> 77% over 3 rounds, but the
  held-out check (1 repeat, and with a since-fixed bug counting 16 provider errors as wrong) showed
  63.3% -> 65.0%, CI [-11.7, +15.0]: NOT significant. Train gains were mostly selection noise/overfit.
- With thinking OFF for scoring: baseline 59.3% vs r3 prompt 67.1% on train+val (biased: r3 was selected
  there). Lower baseline = more headroom; 3x cheaper scoring. Not faster: Luminal throughput ~1 call/s.

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
