# Whetstone: 90-second demo video script

Record at 1080p, browser at ~110% zoom, dark theme. Voice-over in plain language. Total 90 s.

| Time | Shot (what's on screen) | Voice-over |
|---|---|---|
| 0:00-0:10 | Title card: **Whetstone: self-improving prompt optimizer**. Then a plain prompt in a text box. | "Every company running AI has prompts that are 'good enough'. Nobody has time to tune them, and nobody can prove a tweak actually helped." |
| 0:10-0:22 | Dashboard → **Results** tab, `banking77` run. Pan across the score-per-round chart. | "Whetstone fixes that. Give it a prompt, examples, and a scoring rule. A team of AI agents on Luminal proposes better versions in parallel: mutate, crossover, and fresh rewrites." |
| 0:22-0:35 | Hover the dots (each proposal), then the orange line climbing 70% → 85% on validation. Scroll to **Agent feed** (kept vs discarded). | "Each round, every candidate is scored. An analyst agent turns the failures into lessons that guide the next round. Only candidates that beat the champion on validation survive." |
| 0:35-0:48 | **Lessons** panel, then **How the prompt evolved** diff (green "Key distinctions" block). | "Here's what it learned: the confusable labels and the cues that separate them, written into the prompt automatically." |
| 0:48-0:60 | **Held-out card**: 72.0% → 81.5%, "Statistically significant". | "The proof: 400 official test examples the optimizer never saw. Accuracy went from 72 to 81.5 percent. That's a third fewer errors, with a 95% confidence interval that excludes zero." |
| 0:60-0:70 | Slide: "Pilot: a government contractor's internal AI coding pipeline" + the pilot's numbers (tokens per run −X%, same fix rate). | "It's general. We pointed it at a government contractor's internal code-fixing pipeline and cut tokens per run by X percent on held-out work, with the same fix rate." |
| 0:70-0:82 | **Pricing** tab, then **Account & runs**: cost estimate → confirm checkbox. Quick cut of the AWS console (Lambda, DynamoDB, KMS, Cognito, App Monetization plans). | "It's a product: customers sign in with Cognito, bring their own AI key, encrypted with KMS, and see the cost on their own key before every run. Billing runs on AWS App Monetization: $49 founding, $199 standard." |
| 0:82-0:90 | Sales slide: "First customer conversation: [result of the outreach]". Disclose: "The first prospect is my employer." End card with the repo URL. | "And we're selling it. Our first prospect, disclosed: my employer, [status of the yes]. Whetstone: prompts that prove they got better." |

## Shot checklist (Chayce)
- Dashboard (local `python -m whetstone.web` or the public Lambda URL) on the banking77 run.
- Account tab signed in (Wyatt's Cognito login), estimate shown, do not click Start.
- AWS console tabs ready: Lambda function `whetstone-web`, DynamoDB tables, KMS key, Cognito pool, App Monetization app.
- Never show: `.env`, any terminal with keys, the pilot's tool name, code, or logs. Pilot appears only as the slide wording above.
