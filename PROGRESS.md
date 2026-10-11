# Whetstone: Progress

Handoff file. If Claude usage runs out, Codex or a human picks up from here.
The full spec is `claude_code_kickoff_prompt.md`; the approved plan is summarized below.

## Approved plan (Phase 2)

| # | Step | Status |
|---|---|---|
| 1 | Repo & environment | ✅ done |
| 2 | Core library (Luminal client, TaskAdapter interface, objective, frozen split + hash, storage) | ✅ done |
| 3 | Adapter A: text classification (exact match) | ✅ done |
| 4 | Optimizer loop (mutate / crossover / fresh / analyst, selection, budgets, resumable) | ✅ done (banking77: 8 rounds, val 70% → 85%) |
| 5 | Code-fix data: repos → findings → frozen split | ✅ 110 findings, 5 repos, 39 rules; split frozen (`data/codefix/split.json`). Chayce's PR #1 merged as `repos.v2-candidates.yaml` (adds bottle, mako for v2) |
| 6 | Adapter B: code-fix (sandbox, Luminal fixer, re-scan + tests, cache) | ✅ done (verifier self-test passes; dev baseline 6/8 on itsdangerous) |
| ✂ | Cut line 3:00 PM | |
| 7 | Persistence → **DynamoDB** (option A; replaces Atlas) | ✅ done |
| 8 | Held-out evaluation | ✅ banking77 headline (below). Code-fix run `codefix-20261011-160235` in progress (baseline already 82% train / 95% val, little headroom) |
| 9 | Private pilot | ✅ 3 rounds, 8 candidates; held-out (4 runs each): tokens/run −23.3% (non-overlapping ranges), cost −22%, fix time −15% (directional), same fix rate. Public wording only: "a government contractor's internal AI code-fixing tool" |
| 10 | Results UI (FastAPI + HTML) | ✅ done: `python -m whetstone.web` → http://127.0.0.1:8000 |
| ✂ | Cut line 5:00 PM | |
| 11 | Customer features (BYO key, cost estimate, spend limit, run counter, usage log) | ✅ done (KMS) |
| 12a | Payments (AWS App Monetization beta) | 🟡 app + metric `optimization_run` + plans Founding $49 (4 runs) / Standard $199 (10 runs), $5 overage (cap 20) created as **drafts** (sandbox). Seller registration pending (ListApps transport error; asked Wyatt). Code wiring (metering/checkout) next |
| 12b | Deploy | ✅ Lambda + Function URL: https://orluwkuvzjjph76umunjuj6qpe0yzalo.lambda-url.us-east-1.on.aws/ |
| ✂ | Cut line 7:00 PM: features stop | |
| 13 | Sale message draft | 🟡 private draft in `pilot/outreach/` (needs pilot numbers) |
| 14 | Demo video script | |
| 15 | README + submission | |

## Status at ~17:15 ET (latest)

- Headline (T1): banking77 held-out 72.0% → 81.5% (+9.5 pts, CI +5.5..+13.5, significant).
- Deployed: Lambda dashboard (read-only) + DynamoDB + KMS + Cognito (customer sign-in) + ECR.
- AWS monetize skill: HTTP-direct path; app id 01a12c9f8ab07ce0b73c7f317885a5c0 (us-west-2 beta endpoint).
  Connection files `.env.monetization` / `.monetize/` are git-ignored.
- Tonight (ET): pilot numbers ~18:20 → outreach ~18:30 → feature freeze 19:00 → video + README + submit by ~19:45 → judging 20:00.

## Prize targets (decided)

- **T1 Transpose / Luminal** ($3k): core loop + held-out result. Highest priority.
- **T2 Build AND Sell**: both the **Sales prize** (first-customer sale) and the **AWS prize**.
- MongoDB: not entered. Step 7 persistence = **AWS DynamoDB** (counts toward the AWS prize). Chayce: skip Atlas.
- Priority if behind: T1 > Sales > AWS.

## Team

- Wyatt (WyattA-25): lead, reviews and runs everything.
- Chayce (Chayce-Allison): code-fix repo scouting (PR #1), testing, video recording.

## Repo

https://github.com/WyattA-25/Whetstone (private until step 15). Commits use the GitHub noreply email.

## Key decisions

- Optimization objective is configurable (success rate, tokens, time, cost, with constraints).
- Code-fix adapter accepts any scanner that outputs SARIF; parsers for others.
- Fixer inside the loop = Luminal flash model.
- UI = FastAPI + single HTML page. Deploy = App Runner (web); optimization worker runs separately.

## HEADLINE (banking77-20261011-142259, results/banking77-20261011-142259-heldout.json)

- 400 official Banking77 test examples, never used in optimization, hash verified, 0 excluded:
  **baseline 72.0% -> best 81.5%; +9.5 pts [95% CI +5.5, +13.5]; +13.2% relative; error rate -34%; significant.**
- Validation (selection) 70.0% -> 85.0% over 8 rounds; best prompt r4-fresh-2 (fresh-strategy agent, round 4).
- Cost of the whole run: ours $0.05 (agents), theirs $0.82 scoring + $0.15 held-out (placeholder prices).
- Tradeoff (report honestly): the best prompt is ~11x longer (98 -> 1,094 tokens/example; mostly label
  definitions), so per-call cost is ~10x. A follow-up run with objective "minimize tokens, success >= best-2pts"
  is the natural next step (the objective is configurable).

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

## Customer identity (Cognito) — required by the AWS monetize skill

- Cognito user pool `whetstone-customers` (us-east-1_pKCpGo6FW), app client `whetstone-web` (no secret,
  USER_PASSWORD_AUTH). Admin-created accounts only (B2B onboarding). customer_id = Cognito `sub`.
- `whetstone/auth.py`: login + strict ID-token verification (RS256/JWKS, iss, aud, token_use=id, exp).
  Tests: forged/wrong-aud/wrong-iss/access-token/expired/unsigned tokens rejected.
- All account endpoints require `Authorization: Bearer <id token>` (401 otherwise). UI: sign-in form,
  token in sessionStorage only, sign-out.
- Onboard a customer: `python -m whetstone.customers add <email> --copy-demo-keys` (password via hidden prompt).
- AWS monetize skill: in progress (HTTP-direct path, .monetize/integration=http). Next: recommendation.

## Customer features (step 11)

- `whetstone/accounts.py`: plans (Founding $49/4 runs, Standard $199/10 runs, extra $5), run counter per UTC
  month, counting rules, usage log, cost estimate. DynamoDB `whetstone-accounts`.
- Customer API keys: validated with one tiny call (429 = accepted, provider busy), encrypted with KMS
  `alias/whetstone-customer-keys` with encryption context {customer_id, key_id}, never returned/logged,
  revocable. The worker decrypts in memory at run start (`--customer/--key-id`).
- Web: Account tab (local only: WHETSTONE_ACCOUNT_API=on) — keys, plan, estimate → confirm → start,
  extra-run $5 confirm (also enforced server-side + in the CLI), usage log. Pricing tab always on.
- Demo customer id `demo` has our Luminal key registered as its "customer key".
- Verified: ciphertext only at rest; wrong encryption context rejected by KMS; fake key -> 401 shown;
  unconfirmed run -> HTTP 400; 5th Founding run flagged extra and billed $5 unless our bug failed it.

## Deployment (12b)

- Public read-only dashboard on **AWS Lambda (container image from ECR) + Function URL** (App Runner returned
  SubscriptionRequiredException for this account). Role WhetstoneWebLambda: CloudWatch logs + read-only
  DynamoDB whetstone-runs. No secrets in the image; account API off (403).
- Redeploy: `bash scripts/deploy_aws.sh` (set AWS_CLI to the aws.exe path on Windows).
- AWS services in use: DynamoDB, KMS, ECR, Lambda, IAM, CloudWatch Logs. Delete function/ECR/KMS after judging.

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

## Incident (17:40 ET) and the rule it created

- The private pilot drives an external pipeline that runs git commands in its own workspace. Its workspace
  had been placed inside this repo's folder, so on one run those commands acted on THIS repo: `origin` was
  repointed, foreign branches fetched, and `main` moved. Nothing was committed or pushed (dry-run).
- Restored: `origin` reset to GitHub, `main` reset to `origin/main` (every commit had been pushed), stray
  branch deleted; tests pass; all untracked/private files intact. Unreachable foreign objects may remain in
  the local object store until `git gc` (never pushed; harmless to the public repo).
- RULE: external-tool workspaces/configs live OUTSIDE any git repo; the pilot script refuses to run otherwise.

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
- Luminal judging (posted 4:04 PM): measurable improvement incl. fresh tests 40%, loop design 30%,
  effective parallelism 20%, demo clarity 10%; relative improvement + difficulty.
- AWS Track 2: must fill the AWS UserTesting survey after trying the monetize tool (eligibility + $50 card).
- Pilot partner: permission, harness format, model used (resolved).

## Confidentiality

- Partner identifiers go in `configs/private/denylist.txt` (git-ignored, one term per line).
- The pre-commit hook (`.githooks/pre-commit`) blocks pilot paths, `.env`, denylisted terms, and obvious secrets.
