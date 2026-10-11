"""Step 5: turn data/codefix/repos.yaml into a frozen dataset of scanner findings.

For each repo: clone at the pinned commit (into .cache/, outside the tracked tree), make its own
venv, install, confirm the tests pass, scan the source dir, then pick a diverse set of good findings.

Usage:
  python scripts/collect_findings.py                       # all repos in repos.yaml
  python scripts/collect_findings.py --only itsdangerous   # one repo
  python scripts/collect_findings.py --skip-tests          # scan only (quick look)
Output: data/codefix/findings.jsonl  (+ data/codefix/repos.lock.json with resolved commits + timings)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from whetstone.tasks.sandbox import CACHE, sh, venv_env  # noqa: E402
from whetstone.tasks.scanners import scan  # noqa: E402

REPOS_YAML = ROOT / "data/codefix/repos.yaml"
OUT = ROOT / "data/codefix/findings.jsonl"
LOCK = ROOT / "data/codefix/repos.lock.json"

SKIP_PARTS = ("test", "tests", "testing", "docs", "doc", "examples", "example", "vendor", "_vendor", "benchmarks")
# Unfixable without a suppression comment or a behaviour change: warnings about importing/using subprocess
# at all (the library's job is to run subprocesses). Per-repo extras go in repos.yaml (exclude_rules/paths).
EXCLUDE_RULES = {"B404", "S404", "B603", "S603"}
MAX_PER_RULE = 4        # per repo: keeps the dataset diverse
MAX_PER_REPO = 30
SEED = 42


def prepare(repo: dict, run_tests: bool) -> dict:
    name = repo["name"]
    src = CACHE / "repos" / name
    if not src.exists():
        print(f"  cloning {repo['url']}")
        r = sh(["git", "clone", "--quiet", repo["url"], str(src)], cwd=ROOT)
        if r.returncode:
            raise RuntimeError(r.stderr)
    commit = repo.get("commit", "HEAD")
    r = sh(["git", "checkout", "--quiet", commit], cwd=src)
    if r.returncode:
        raise RuntimeError(f"checkout {commit} failed: {r.stderr}")
    resolved = sh(["git", "rev-parse", "HEAD"], cwd=src).stdout.strip()
    lock = {"name": name, "url": repo["url"], "commit": resolved}

    if run_tests:
        venv = CACHE / "venvs" / name
        if not venv.exists():
            print("  creating venv + installing")
            sh([sys.executable, "-m", "venv", str(venv)], cwd=ROOT)
            env = venv_env(venv)
            sh("python -m pip install -q --upgrade pip", cwd=src, env=env)
            r = sh(repo.get("install", "pip install -e . pytest"), cwd=src, env=env)
            if r.returncode:
                raise RuntimeError(f"install failed: {r.stderr[-500:]}")
        env = venv_env(venv)
        t = time.time()
        r = sh(repo.get("test", "pytest -x -q"), cwd=src, env=env, timeout=300)
        lock["test_seconds"] = round(time.time() - t, 1)
        lock["tests_pass"] = r.returncode == 0
        print(f"  tests: {'PASS' if r.returncode == 0 else 'FAIL'} in {lock['test_seconds']}s")
        if r.returncode:
            raise RuntimeError(f"tests fail on a clean checkout:\n{r.stdout[-800:]}")
    return lock


def good(f, source_dir: str, repo: dict | None = None) -> bool:
    repo = repo or {}
    if f.rule in EXCLUDE_RULES or f.rule in repo.get("exclude_rules", []):
        return False
    if any(x in f.path for x in repo.get("exclude_paths", [])):
        return False
    parts = Path(f.path).parts
    if not f.path.startswith(source_dir.rstrip("/")):
        return False
    if any(p.lower() in SKIP_PARTS or p.startswith("test_") for p in parts):
        return False
    return f.rule not in ("syntax",)


def collect(repo: dict) -> list[dict]:
    src = CACHE / "repos" / repo["name"]
    found = []
    for tool in repo.get("scanners", ["ruff", "bandit"]):
        found += scan(tool, src, repo["source_dir"])
    found = [f for f in found if good(f, repo["source_dir"], repo)]
    # de-duplicate the same rule on the same line (ruff's S rules mirror bandit's)
    uniq = {}
    for f in found:
        num = f.rule[1:] if f.rule[:1] in ("S", "B") and f.rule[1:].isdigit() else f.rule
        uniq.setdefault((f.path, f.line, num), f)
    found = sorted(uniq.values(), key=lambda f: (f.path, f.line, f.rule))

    rng = random.Random(f"{SEED}:{repo['name']}")
    by_rule = defaultdict(list)
    for f in found:
        by_rule[(f.tool, f.rule)].append(f)
    picked = []
    for key in sorted(by_rule):
        items = by_rule[key]
        picked += rng.sample(items, min(MAX_PER_RULE, len(items)))
    picked = sorted(rng.sample(picked, min(MAX_PER_REPO, len(picked))), key=lambda f: (f.path, f.line))

    rows = []
    for f in picked:
        fid = hashlib.sha1(f"{repo['name']}|{f.tool}|{f.rule}|{f.path}|{f.line}".encode()).hexdigest()[:10]
        rows.append({"id": f"{repo['name']}-{f.rule}-{fid}", "repo": repo["name"], **f.as_dict()})
    print(f"  findings: {len(found)} good candidates across {len(by_rule)} rules -> picked {len(rows)}")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--skip-tests", action="store_true")
    ap.add_argument("--repos", default=str(REPOS_YAML))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.repos).read_text(encoding="utf-8"))
    repos = [r for r in cfg["repos"] if not args.only or r["name"] == args.only]
    rows, locks = [], []
    for repo in repos:
        print(f"[{repo['name']}]")
        try:
            locks.append(prepare(repo, run_tests=not args.skip_tests))
            rows += collect(repo)
        except Exception as e:
            print(f"  SKIPPED: {e}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    lock = LOCK if out == OUT else out.with_name("repos.lock.json")
    lock.write_text(json.dumps(locks, indent=2), encoding="utf-8")
    print(f"\nwrote {len(rows)} findings from {len(locks)} repos -> {out}  (commits + test times: {lock})")
    print("Next: the code-fix adapter freezes the train/val/held-out split on first use.")


if __name__ == "__main__":
    main()
