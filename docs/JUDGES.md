# For judges: what we built, which prizes we're going for, and the evidence

**Whetstone** is a general-purpose, self-improving **prompt optimizer**: a team of AI agents running in parallel evolves a prompt over repeated rounds, and every claim is checked on held-out data the optimizer never saw.

## Tracks we are entering (transparently)

| Track / prize | Why we qualify | Where to look |
|---|---|---|
| **Transpose: "Build a Self-Improving Agent Team" (Luminal)** | Parallel agents (mutate / crossover / fresh + analyst) run on **Luminal's DeepSeek-V4.1-Flash** and improve a solution over rounds, measured on fresh held-out tests | Sections 1-4 below, `whetstone/run.py`, `whetstone/agents.py`, `results/` |
| **Build AND Sell: Sales prize** | Real outreach to two executives at AI-developer-tool companies with measured results and a concrete price; status log below | Section 6 |
| **Build AND Sell: AWS prize** | Seven AWS services in production use, including the **AWS App Monetization private beta** for subscriptions with metered extra-run pricing | Section 5 |

We did **not** enter the MongoDB prize: persistence moved to Amazon DynamoDB to keep the stack on AWS.

## 1. Measurable improvement, including on fresh tests (Luminal 40%)

| Task | Baseline → best on held-out data | Significance |
|---|---|---|
| Support-ticket intent classification (Banking77, 10 confusable intents) | **72.0% → 81.5%** on all **400 official test examples** (never used in tuning) | Paired bootstrap 95% CI **+5.5 to +13.5 pts**; error rate −34% |
| A government contractor's internal AI code-fixing pipeline (private pilot, dry-run) | **Tokens per run −23.3%**, cost −22%, fix time −15%, **same fix rate** (3/3 findings every run) | Held-out findings, 4 runs per prompt; token ranges don't overlap (best 88k-109k vs baseline 125k-143k). Time gain is directional |
| Code-fix showcase (110 ruff/bandit findings, 5 OSS repos) | 93.9% → 90.9% (no gain) | Reported as-is: the baseline was at its ceiling; the guardrails don't invent gains |

**Problem difficulty.** The Banking77 subset uses 10 deliberately confusable intents (pending vs failed vs declined transfers and top-ups). The pilot targets a production agentic pipeline where every evaluation is a real Codex fix verified by build, tests, and re-scan.

**Held-out integrity.** Splits are frozen with a SHA-256 hash recorded at creation and verified before final evaluation (`whetstone/split.py`). Held-out examples can only be read with `final_eval=True`, and the loop asserts they are never used for selection or lessons. Provider errors (429/503) are retried and never scored as wrong answers (`whetstone/evaluate.py`, `whetstone/final_eval.py`).

## 2. Improvement-loop design (Luminal 30%)

Each round (`whetstone/run.py`):
1. An **analyst agent** turns the current champion's training failures into general lessons (`agents.analyze`).
2. **Proposers with different strategies** run: *mutate* (targeted edits), *crossover* (combine the top two), and *fresh* (a new approach). Lessons and measured scores from earlier rounds are in their context.
3. Candidates and the champion are scored on the **same fresh seeded minibatch** (paired comparison).
4. The top challengers are re-checked on validation. The champion's validation score is a **running mean** across rechecks, which fixes the winner's curse we observed. A candidate is promoted only if it beats that.
5. The **objective is configurable**: maximize success, or minimize tokens, time, or cost subject to "success within X of baseline". The pilot used tokens plus time with success held.

What we learned, visible in the commit history: v1 overfit (train +11 pts, held-out +1.7, not significant). We redesigned around an official test set, paired minibatches, and running-mean selection, and v2 was significant.

## 3. Effective parallelism (Luminal 20%)

- 4-6 proposer agents run **concurrently** each round, and every candidate's evaluation fans out in parallel under a shared concurrency limit (8, tuned to Luminal's ~10-concurrent rate limit, with exponential backoff).
- Strategy diversity pays off: winners came from different strategies (Banking77: mutate in round 1, then crossover, then fresh; pilot: crossover in round 3).
- The pilot ran 4 dry-run pipeline jobs in parallel in isolated workspaces.

## 4. Demo and clarity (Luminal 10%)

- 90-second video (link in the submission). The script is in `docs/video_script.md`.
- Public dashboard on AWS Lambda: https://orluwkuvzjjph76umunjuj6qpe0yzalo.lambda-url.us-east-1.on.aws/ (score per round, every agent's proposal, the analyst's lessons, prompt diff, held-out card).
- Reproduce: `python -m whetstone.run --task banking77 --rounds 8` then `python -m whetstone.final_eval <run_id>` (see README).

## 5. How we used AWS (AWS prize)

| Service | What it does in Whetstone | Detail worth noting |
|---|---|---|
| **AWS App Monetization (private beta)** | Plans, checkout, billing portal, metering, entitlements | Two subscription plans (Founding $49/mo with 4 runs, Standard $199/mo with 10) with **metered overage at $5 per extra run** (`APPLY_FIXED_OVERAGE`, capped at 20). Each counted run emits one idempotent `optimization_run` event, keyed on the run id. **Entitlement is checked before every run and fails closed.** Hosted pricing, checkout, and billing portal mean zero billing UI code. Python has no SDK, so we integrated over **SigV4-signed HTTP** (`whetstone/billing.py`) |
| **Amazon Cognito** | Customer sign-up and sign-in | Email-verified self sign-up. The verified ID token's `sub` is the billing identity. Tokens are checked for signature, issuer, audience, token use, and expiry (`whetstone/auth.py`, with tests) |
| **AWS KMS** | Encrypts customers' AI-provider API keys at rest | Encryption context binds each ciphertext to `{customer_id, key_id}`, so a copied blob won't decrypt. Keys are never logged or returned; the worker decrypts in memory; yearly rotation is on |
| **Amazon DynamoDB** | Run history, accounts, run counter, usage log | On-demand tables. Runs write locally first, then to DynamoDB with the same sequence number, so a backfill (`whetstone.sync`) is idempotent and outages never stop a run. The dashboard reads straight from it |
| **AWS Lambda + Function URL** | Hosts the public dashboard (FastAPI via Mangum) | Container image, no secrets in the image, account API disabled on the public deployment. App Runner was the plan, but this account isn't enabled for it, so we pivoted the same day |
| **Amazon ECR** | Container registry for the dashboard image | Scan-on-push enabled |
| **AWS IAM** | Least privilege | The Lambda role can only **read** the runs table (plus logs). The runtime App Monetization policy is documented in `PROGRESS.md` |

**Business model, enforced in code.** Our agents run on our Luminal account. **Scoring (90%+ of a run's tokens) runs on the customer's own AI key**, so the prompt is optimized on the model they use in production and margins hold. Before every run the customer sees an estimate (examples × candidates × rounds × tokens × their price), sets a per-run spending limit, and confirms. Extra runs require an explicit $5 confirmation, enforced in the UI, API, and CLI.

## 6. Sales: who we contacted and what happened

We're transparent that **our first prospect is my employer**, a government contractor that builds AI developer tools.

| # | Prospect | What we offered | Status |
|---|---|---|---|
| 1 | **CEO of my employer** (government contractor, AI developer tools). Disclosed: I work there | Ran a dry-run pilot on their internal AI code-fixing pipeline (−23% tokens per run, same fix rate). Offered the Founding plan: $49/mo locked 12 months, 4 runs, $5 per extra run, scoring on their own OpenAI account (about $1-2 per run) | **Positive.** "That sounds exciting." He referred us to their technical lead to evaluate. Message sent to the technical lead; *awaiting reply* |
| 2 | **Executive at a second company** building AI products | Confirmed they use AI prompts in one product today with more planned; sent results and the Founding offer | *Awaiting reply* |

*This table is updated as replies come in.* Payments run in the App Monetization **sandbox** (the beta processes test payments only), so a written yes or a letter of intent is the strongest commitment possible today. The seller payout registration is created.

## 7. Honest limitations

See the README's "Honest limitations": small pilot samples, longer prompts, process-level sandboxing, the beta billing sandbox, and Luminal rate limits and 503s during the event. Nothing from the employer pilot (code, prompts, data, names) is in this repository. It ran from a private, git-ignored folder, with a pre-commit guard that blocks employer terms.
