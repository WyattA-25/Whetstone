# Data attribution

`banking77_subset.jsonl` is a 200-example subset (10 intents x 20) of the **Banking77** test split
by PolyAI, licensed **CC-BY-4.0**. Built with `scripts/build_banking77.py` (seed 42).

Casanueva et al., "Efficient Intent Detection with Dual Sentence Encoders", 2020.
https://github.com/PolyAI-LDN/task-specific-datasets

`../banking77/banking77_v2.jsonl` (task `banking77`): train 120 / val 80 sampled from the Banking77 **train**
file (12 + 8 per intent, seed 42, excluding 6 texts that also appear in the test file); held-out = all 400
Banking77 **test** examples for the same 10 intents. Built with `scripts/build_banking77_v2.py`.
