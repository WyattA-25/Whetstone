# Linguist

**A self-improving prompt optimizer.** Give Linguist a prompt you already use, a set of example inputs, and a way to score outputs. A team of AI agents evolves better versions of that prompt over repeated rounds and proves the improvement on held-out examples the optimizer never saw.

Works for any prompt-driven task: support replies, classification, data extraction, summarization, sales emails, coding agents. Our first showcase is a code-fix pipeline, where an AI agent fixes scanner findings and success is checked objectively by re-scanning and running the tests.

> 🚧 Built during a one-day hackathon. Work in progress.

## How it works (short)

1. **Baseline:** score the current prompt on training examples.
2. **Propose:** parallel agents (mutate, crossover, fresh, and an analyst that writes "lessons" from failures) propose new prompt variants.
3. **Evaluate & select:** score each variant through a pluggable *task adapter*; keep the best.
4. **Repeat** until rounds or budget run out.
5. **Final test:** baseline vs. best on a frozen held-out set.

The objective is configurable: maximize success rate, or minimize tokens, time, or cost while keeping success above a floor.

## Setup

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows; use .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env          # then fill in keys
git config core.hooksPath .githooks
```

## Status

See [PROGRESS.md](PROGRESS.md).
