# Step 5 helper prompt: scouting code-fix demo repos

**For Chayce.** Paste everything below the line into Claude (Claude Code, or claude.ai with a terminal
available). It walks you through finding and vetting the repos for our code-fix test case and
produces a file the main build can consume directly.

---

You're helping me with one well-defined task during a one-day hackathon. Please guide me step by step,
run (or tell me to run) the commands, and check results with me before moving on. I'm comfortable in a
terminal but not an expert. Ask me what OS I'm on before giving any commands.

## Context (what the project is)

Our project, **Whetstone**, is a general-purpose *prompt optimizer*: AI agents repeatedly rewrite a prompt,
score each version on example tasks, and keep the winners. One of our showcase tasks is **code fixing**:
a static-analysis scanner reports a finding in some open-source code, an AI model is given our prompt +
the finding + the file, and it must produce a fix. A fix counts as successful only if:

1. re-running the scanner no longer reports that finding,
2. the repo's test suite still passes, and
3. no new findings were introduced.

The optimizer will run each finding many times (dozens of prompt variants × many findings), so
**speed and determinism matter more than anything**. Your job is to find the repositories those
findings come from.

## What I need from you, Claude

Help me shortlist **3 to 5 small, public Python repositories** that meet ALL of these criteria, then
record them in a YAML file (format at the bottom).

### Hard requirements (reject the repo if any fails)

1. **Permissive license**: MIT, BSD, or Apache-2.0. (We'll show code in a public video.)
2. **Pure Python, small**: roughly 1k–15k lines of source. No compiled extensions (Cython/C/Rust),
   no required database, Docker, network services, GPUs, or API keys to run tests.
3. **Tests pass on a fresh clone** with Python 3.11, in a fresh virtual environment, in **under 60 seconds**
   (ideally under 20). Use `pytest -x -q` and time it. Flaky tests = reject.
4. **Installs cleanly**: `pip install -e .` (or `pip install -e ".[test]"` / a requirements-dev file)
   works without errors.
5. **Has real findings** from at least one scanner below, located in the package's **source code, not in
   tests/, docs/, examples/, or vendored code**.

### Scanners to run (from the repo root, inside its venv)

```
pip install ruff bandit
ruff check --select E,F,B,S,SIM,C4,PERF,PL,RUF,UP --output-format json --exit-zero <source_dir> > ruff.json
bandit -r <source_dir> -f json -o bandit.json --exit-zero
```

Use the specific rule families above, **not** `--select ALL`. `ALL` includes pure style rules
(docstrings, type annotations, quote style, trailing commas) that make boring, low-signal findings.
We want findings that are about correctness, security, simplification, or performance.

Then help me summarize: total findings per tool, the top 10 rule codes by count, and how many of those
findings are in source files vs tests.

### What makes a finding GOOD for us (prefer these)

- Fixable by editing **one file**, usually a few lines.
- Has an **unambiguous** "fixed" state the scanner will confirm (the warning disappears).
- Not trivially auto-fixable by `ruff --fix` alone is a plus (more interesting), but not required.
- Covered by tests is a plus (the "tests still pass" check then means something).
- Examples of good ones: bugbear `B006` (mutable default argument), `B904` (raise without from),
  `SIM` simplifications, `PERF` loop issues, `PLR` complexity-light items, bandit `B602`/`B603`
  (subprocess with shell=True), `B324` (weak hash), `B108` (hardcoded /tmp), `S113` (requests without timeout).

### What makes a finding BAD (avoid)

- Requires changing multiple files or public APIs.
- Is a false positive the "fix" would require a `# noqa` comment for. We don't count suppressions as fixes.
- Is in generated code, vendored code, or tests.
- Line-length/formatting only (`E501` etc.).

## Process I'd like you to guide me through

1. **Brainstorm ~10 candidates** of small, well-known permissively-licensed Python libraries (utility
   libraries, parsers, CLI helpers, small web helpers). Tell me why each might fit. I'll pick which to try.
2. **For each candidate**, one at a time:
   - clone it into a scratch folder (NOT inside our Whetstone repo),
   - record the exact commit SHA (`git rev-parse HEAD`),
   - make a fresh venv, install, run the tests with timing,
   - run both scanners and summarize the findings,
   - give a verdict: ✅ keep / ❌ reject (with the reason).
3. Stop once we have **3–5 keepers with at least 60–90 good findings total**, spread across different
   rule types (not 80 copies of the same rule).
4. **(Optional bonus)** Check `bridgecrewio/terragoat` (Terraform) with
   `trivy config --format json -o trivy.json .`: count findings. No tests needed for that one.
5. Write the YAML file below and help me double-check it.

## Safety rules

- Only clone repos from well-known public sources; run their tests only inside their own venv, in a scratch
  folder outside our project.
- Never paste API keys, tokens, or connection strings anywhere, including into this chat.
- Don't commit anything into the Whetstone repo except the final `data/codefix/repos.yaml`.

## Output: `data/codefix/repos.yaml` (exact format)

```yaml
repos:
  - name: example-lib                      # short name
    url: https://github.com/owner/example-lib
    commit: 0123456789abcdef0123456789abcdef01234567   # full SHA you tested
    license: MIT
    python: "3.11"
    install: pip install -e ".[test]"      # exact command that worked
    test: pytest -x -q                     # exact command that worked
    test_seconds: 12.4
    source_dir: src/example_lib            # where findings should come from
    findings:
      ruff: 41                             # in source_dir only, with the rule set above
      bandit: 6
      top_rules: [B006, SIM108, UP032, B904, PERF401]
    notes: "Fast tests, good mix of bugbear findings."
  # ...3 to 5 repos total
rejected:
  - url: https://github.com/owner/other-lib
    reason: "tests take 4 minutes"
```

When the file is done, tell me to send it to Wyatt (or commit it to `data/codefix/repos.yaml` on a branch
and open a PR), and post the summary (repo, test time, finding counts) into `PROGRESS.md` under
"Open questions → code-fix repos".
