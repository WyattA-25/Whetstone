# Whetstone: 90-second demo video (voiceover script)

Build the video: `python scripts/record_demo.py` (automated segments), add your two clips to `video/user/`
(`checkout.mp4`, `run.mp4`), then `python scripts/stitch_demo.py`, which gives `video/whetstone_demo.mp4` (~88 s).
On-screen captions carry every number, so the voiceover can be read at a relaxed pace (~2.6 words/s).
Anything that doesn't fit here is in [docs/JUDGES.md](JUDGES.md).

| Time | On screen | Voiceover | Prize it serves |
|---|---|---|---|
| 0:00-0:03 | Intro card | "Whetstone: a self-improving prompt optimizer." | All |
| 0:03-0:14 | **Sign-up portal** (Cognito), 6-digit code screen | "Every company running AI has prompts that are only 'good enough'. A customer signs up, secured by Amazon Cognito with email verification…" | AWS |
| 0:14-0:29 | **AWS hosted pricing → checkout** ($49.00 invoice) | "…and picks a plan on AWS App Monetization's hosted pricing page. Founding is forty-nine dollars a month for four optimization runs, and extra runs are metered at five dollars each." | AWS, Sales |
| 0:29-0:37 | *Your clip:* test card, back on Founding | "Checkout runs in the sandbox. Their subscription now gates every run." | AWS |
| 0:37-0:47 | *Your clip:* estimate → confirm → start | "They bring their own AI key, encrypted with KMS, see the exact cost estimate on that key, and start a run." | AWS, Sales |
| 0:47-1:15 | **Results tour**: held-out card → chart → agent feed → lessons → diff | "Each round, four agents on Luminal propose new prompts in parallel: mutating, combining, and rewriting from scratch. An analyst agent turns failures into lessons for the next round. Only prompts that beat the champion survive. The proof is on 400 test examples it never saw: 72 to 81.5 percent, a third fewer errors, statistically significant, for under a dollar." | Luminal (improvement, loop design, parallelism) |
| 1:15-1:19 | **Built on AWS** card | "It's all on AWS: Cognito, KMS, DynamoDB, Lambda, and App Monetization for subscriptions plus metered usage." | AWS |
| 1:18-1:26 | **Selling it today** card | "We pitched a government contractor that builds AI systems, after cutting tokens 23 percent on one of their internal tools. Their CEO is interested but wants the CTO's take first. No sale closed today." | Sales |
| 1:26-1:29 | Outro | "Whetstone: prompts that prove they got better." | All |

## Recording tips
- Record the voiceover separately (phone or laptop mic) and drop it under the video in Clipchamp, CapCut, or any editor. Captions already cover every number if you skip narration.
- If a prospect replies, edit `SALES` in `scripts/record_demo.py`, run `python scripts/record_demo.py 06c_sales`, then re-run the stitcher.
- Never show `.env`, a pasted API key, a terminal, or any name of the pilot's tool or company.
