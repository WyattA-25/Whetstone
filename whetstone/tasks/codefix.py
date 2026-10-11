"""Adapter B: fix one static-analysis finding in a real open-source repo.

A fix counts only if (1) the re-scan no longer reports that finding (and it didn't just move),
(2) no new findings appear in the file, and (3) the repo's test suite still passes. Suppression
comments (noqa / nosec) never count. All model-written code runs in a throwaway copy.

The optimizable prompt is the fixer's system message. The adapter's harness (finding, numbered
file, edit format) stays fixed so every prompt variant is scored on the same footing.

Self-test of the verifier:  python -m whetstone.tasks.codefix --selftest
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import threading
import time
from collections import Counter
from pathlib import Path

import yaml

from ..adapter import Example, Output, Score, TaskAdapter
from ..llm import LLMClient
from .sandbox import CACHE, ROOT, repo_dir, sh, venv_dir, venv_env, working_copy
from .scanners import Finding, scan

DATA = ROOT / "data/codefix"
VERIFY_CACHE = CACHE / "verify"
MAX_FILE_LINES = 400       # whole file if shorter; otherwise a window around the finding + the header
WINDOW = 60
TEST_TIMEOUT = 180

HARNESS = """FINDING
tool: {tool}
rule: {rule}
message: {message}
file: {path}
line: {line}

FILE ({shown}; each line is prefixed with its line number and a | which are NOT part of the code)
{numbered}

OUTPUT FORMAT (required)
Return one or more edits. Each edit replaces original lines START..END (inclusive) with new code:
<edit start="START" end="END">
new code lines, with correct indentation
</edit>
To insert without replacing, use end = start - 1 (inserts before line START). To delete, leave the body empty.
Line numbers always refer to the ORIGINAL file shown above. Edits must not overlap.
Return only the edits."""

EDIT_RE = re.compile(r'<edit\s+start\s*=\s*"?(\d+)"?\s+end\s*=\s*"?(\d+)"?\s*>\n?(.*?)</edit>', re.S | re.I)


def parse_edits(text: str, n_lines: int) -> list[tuple[int, int, list[str]]]:
    edits = []
    for s, e, body in EDIT_RE.findall(text):
        s, e = int(s), int(e)
        if body.endswith("\n"):
            body = body[:-1]
        if not (1 <= s <= n_lines + 1 and s - 1 <= e <= n_lines):
            raise ValueError(f"edit range {s}-{e} outside file (1-{n_lines})")
        edits.append((s, e, body.split("\n") if body.strip() else []))
    if not edits:
        raise ValueError("no <edit> blocks found")
    edits.sort()
    for (s1, e1, _), (s2, _, _) in zip(edits, edits[1:]):
        if s2 <= e1:
            raise ValueError("overlapping edits")
    return edits


def apply_edits(lines: list[str], edits) -> list[str]:
    out = list(lines)
    for s, e, new in sorted(edits, reverse=True):
        out[s - 1:e] = new
    return out


def map_region(line: int, edits) -> tuple[int, int]:
    """Where original `line` ends up after the edits: a single line, or the replacement block it fell in."""
    offset = 0
    for s, e, new in edits:
        if e < line:                                      # edit (or insertion) entirely before the line
            offset += len(new) - (e - s + 1)
        elif s <= line <= e:                              # line was inside a replaced block
            start = s + offset
            return start, max(start, start + len(new) - 1)
    return line + offset, line + offset


class CodeFixAdapter(TaskAdapter):
    name = "codefix"
    scoring_timeout = 180.0
    proposals_per_round = 4
    description = (
        "The prompt is the SYSTEM message for an AI coding agent that fixes ONE static-analysis finding "
        "(ruff or bandit) in a Python file from a real open-source repository. A fixed harness supplies the "
        "finding, the numbered source file, and the required <edit> output format, so the prompt should focus "
        "on HOW to fix well. A fix counts only if: the re-scan no longer reports the finding; no new scanner "
        "findings appear in the file; and the repository's test suite still passes. Suppression comments "
        "(# noqa, # nosec) are rejected. Behaviour must be preserved.")

    def __init__(self, findings: Path = DATA / "findings.jsonl", repos: Path = DATA / "repos.yaml"):
        if not findings.exists():
            raise FileNotFoundError(f"{findings} missing: run scripts/collect_findings.py first")
        self._rows = [json.loads(l) for l in findings.read_text(encoding="utf-8").splitlines() if l]
        cfg = yaml.safe_load(repos.read_text(encoding="utf-8"))
        self.repos = {r["name"]: r for r in cfg["repos"]}
        for name in {r["repo"] for r in self._rows}:
            if not repo_dir(name).exists():
                raise FileNotFoundError(f"clone for {name} missing: run scripts/collect_findings.py")
        self._before: dict[str, Counter] = {}
        self._lock = threading.Lock()

    # ---- TaskAdapter --------------------------------------------------------------------------
    def starting_prompts(self) -> list[str]:
        # A plain, realistic first version of a fixer prompt.
        return ["You are a helpful coding assistant. Fix the issue reported by the static analysis tool "
                "in the given Python file. Make minimal changes."]

    def examples(self) -> list[Example]:
        return [Example(id=r["id"], input=r, expected=None, meta={"repo": r["repo"]}) for r in self._rows]

    def render(self, f: dict) -> tuple[str, int]:
        lines = (repo_dir(f["repo"]) / f["path"]).read_text(encoding="utf-8").split("\n")
        n = len(lines)
        if n <= MAX_FILE_LINES:
            idx, shown = range(1, n + 1), f"whole file, {n} lines"
        else:
            header = range(1, min(40, n) + 1)
            win = range(max(41, f["line"] - WINDOW), min(n, f["end_line"] + WINDOW) + 1)
            idx, shown = list(header) + list(win), f"lines 1-40 and {win.start}-{win.stop - 1} of {n}"
        numbered = "\n".join(f"{i:>4}| {lines[i - 1]}" for i in idx)
        return HARNESS.format(tool=f["tool"], rule=f["rule"], message=f["message"], path=f["path"],
                              line=f["line"], shown=shown, numbered=numbered), n

    def run(self, prompt: str, example: Example, llm: LLMClient) -> Output:
        user, _ = self.render(example.input)
        r = llm.chat([{"role": "system", "content": prompt}, {"role": "user", "content": user}],
                     temperature=0, max_tokens=8192)
        return Output(r.text, r.prompt_tokens, r.completion_tokens, r.usd, r.seconds)

    def score(self, example: Example, output: Output) -> Score:
        f = example.input
        path = repo_dir(f["repo"]) / f["path"]
        lines = path.read_text(encoding="utf-8").split("\n")
        try:
            edits = parse_edits(output.text, len(lines))
        except ValueError as e:
            return Score({"success": 0.0, "parse_ok": 0.0}, self._note(f, f"unusable output: {e}", output.text))
        new_lines = apply_edits(lines, edits)
        added = "\n".join(l for _, _, new in edits for l in new)
        if re.search(r"#\s*(noqa|nosec)", added, re.I):
            return Score({"success": 0.0, "parse_ok": 1.0, "suppressed": 1.0},
                         self._note(f, "used a suppression comment instead of fixing", added))
        v = self.verify(f, "\n".join(new_lines), edits)
        m = {"success": float(v["fixed"] and v["no_new"] and v["tests_pass"]), "parse_ok": 1.0,
             "rescan_clean": float(v["fixed"]), "no_new_findings": float(v["no_new"]),
             "tests_pass": float(v["tests_pass"]), "verify_seconds": v["seconds"]}
        if m["success"]:
            return Score(m)
        why = []
        if not v["fixed"]:
            why.append("the scanner still reports the finding")
        if not v["no_new"]:
            why.append(f"new findings introduced: {v['new']}")
        if not v["tests_pass"]:
            why.append(f"tests fail: {v['test_tail']}")
        return Score(m, self._note(f, "; ".join(why), added))

    # ---- verification -------------------------------------------------------------------------
    def _note(self, f: dict, why: str, edit: str) -> str:
        return (f"finding: {f['tool']} {f['rule']} ({f['message']}) at {f['path']}:{f['line']}\n"
                f"result: {why}\nmodel's edit (first 400 chars): {edit.strip()[:400]!r}")

    def _scan_file(self, root: Path, rel: str) -> list[Finding]:
        return scan("ruff", root, rel) + scan("bandit", root, rel)

    def _before_counts(self, f: dict) -> Counter:
        key = f"{f['repo']}/{f['path']}"
        with self._lock:
            if key not in self._before:
                self._before[key] = Counter((x.tool, x.rule) for x in self._scan_file(repo_dir(f["repo"]), f["path"]))
            return self._before[key]

    def verify(self, f: dict, new_text: str, edits) -> dict:
        key = hashlib.sha256(f"{f['id']}\n{new_text}".encode()).hexdigest()
        cached = VERIFY_CACHE / f"{key}.json"
        if cached.exists():
            return json.loads(cached.read_text())
        t = time.time()
        repo = self.repos[f["repo"]]
        before = self._before_counts(f)
        with working_copy(f["repo"]) as wc:
            (wc / f["path"]).write_text(new_text, encoding="utf-8")
            after_list = self._scan_file(wc, f["path"])
            after = Counter((x.tool, x.rule) for x in after_list)
            target = (f["tool"], f["rule"])
            lo, hi = map_region(f["line"], edits)
            still_there = any((x.tool, x.rule) == target and lo <= x.line <= hi for x in after_list)
            fixed = not still_there and after[target] <= before[target] - 1
            new = {f"{t_}:{r_}": after[(t_, r_)] - before[(t_, r_)] for (t_, r_) in after
                   if (t_, r_) != target and after[(t_, r_)] > before[(t_, r_)]}
            src_root = wc / Path(repo["source_dir"]).parent
            env = venv_env(venv_dir(f["repo"]), {"PYTHONPATH": str(src_root), "PYTHONDONTWRITEBYTECODE": "1"})
            try:
                r = sh(repo.get("test", "pytest -x -q"), cwd=wc, env=env, timeout=TEST_TIMEOUT)
                tests_pass, tail = r.returncode == 0, (r.stdout + r.stderr).strip()[-300:]
            except subprocess.TimeoutExpired:
                tests_pass, tail = False, f"timed out after {TEST_TIMEOUT}s"
        res = {"fixed": fixed, "no_new": not new, "new": new, "tests_pass": tests_pass,
               "test_tail": "" if tests_pass else tail, "seconds": round(time.time() - t, 2)}
        VERIFY_CACHE.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(res))
        return res


def selftest(a: "CodeFixAdapter") -> None:
    """Prove the verifier can't be fooled: no-op fails, breaking change fails, tests import the sandbox."""
    ex = a.examples()[0]
    f = ex.input
    lines = (repo_dir(f["repo"]) / f["path"]).read_text(encoding="utf-8").split("\n")
    noop = f'<edit start="{f["line"]}" end="{f["line"]}">\n{lines[f["line"] - 1]}\n</edit>'
    s = a.score(ex, Output(noop))
    print(f"1. no-op edit          -> success={s.success:.0f} rescan_clean={s.metrics['rescan_clean']:.0f}  (expect 0, 0)")
    supp = f'<edit start="{f["line"]}" end="{f["line"]}">\n{lines[f["line"] - 1]}  # noqa\n</edit>'
    s = a.score(ex, Output(supp))
    print(f"2. noqa suppression    -> success={s.success:.0f} suppressed={s.metrics.get('suppressed', 0):.0f}  (expect 0, 1)")
    brk = '<edit start="1" end="0">\nraise RuntimeError("sandbox canary")\n</edit>'
    s = a.score(ex, Output(brk))
    print(f"3. breaking change     -> success={s.success:.0f} tests_pass={s.metrics['tests_pass']:.0f}  (expect 0, 0)")
    repo = a.repos[f["repo"]]
    pkg = Path(repo["source_dir"]).name
    with working_copy(f["repo"]) as wc:
        env = venv_env(venv_dir(f["repo"]), {"PYTHONPATH": str(wc / Path(repo["source_dir"]).parent)})
        r = sh(["python", "-c", f"import {pkg}; print({pkg}.__file__)"], cwd=wc, env=env)
        print(f"4. tests import from   -> {r.stdout.strip()}\n   sandbox copy? {str(wc) in r.stdout}  (expect True)")
    print(f"5. original untouched  -> {(repo_dir(f['repo']) / f['path']).read_text(encoding='utf-8').split(chr(10)) == lines}  (expect True)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--findings", default=str(DATA / "findings.jsonl"))
    ap.add_argument("--repos", default=str(DATA / "repos.yaml"))
    args = ap.parse_args()
    if args.selftest:
        selftest(CodeFixAdapter(Path(args.findings), Path(args.repos)))
