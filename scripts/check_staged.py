"""Pre-commit guard: block secrets, pilot data, and partner identifiers.

Partner terms live in configs/private/denylist.txt (git-ignored), so the
denylist itself never leaks into the repo.
"""
import re
import subprocess
import sys
from pathlib import Path

BLOCKED_PATHS = [
    re.compile(r"(^|/)\.env($|\.)(?!example$)"),
    re.compile(r"(^|/)pilot/"),
    re.compile(r"(^|/)configs/private/"),
    re.compile(r"\.private\."),
    re.compile(r"(^|/)\.npmrc$"),
    re.compile(r"(^|/)\.claude/(skills|commands)/"),
    re.compile(r"monetiz", re.I),                           # AWS beta skill files are confidential
]

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),                 # OpenAI-style keys
    re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),             # Anthropic keys
    re.compile(r"AKIA[0-9A-Z]{16}"),                       # AWS access key id
    re.compile(r"mongodb(\+srv)?://[^\s:/]+:[^\s@/]+@"),   # Mongo URI with password
    re.compile(r"(sk|rk)_live_[A-Za-z0-9]{10,}"),          # Stripe live keys
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"_authToken\s*=\s*\S{8,}"),                # npm registry tokens (.npmrc)
]

DENYLIST = Path("configs/private/denylist.txt")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace", check=True
    ).stdout


def main() -> int:
    staged = [p for p in git("diff", "--cached", "--name-only", "--diff-filter=ACMR").splitlines() if p]
    terms = []
    if DENYLIST.exists():
        terms = [t.strip().lower() for t in DENYLIST.read_text(encoding="utf-8").splitlines() if t.strip() and not t.startswith("#")]

    problems = []
    for path in staged:
        if any(p.search(path) for p in BLOCKED_PATHS):
            problems.append(f"{path}: blocked path")
            continue
        if path == "scripts/check_staged.py":
            continue  # contains the patterns themselves
        try:
            content = git("show", f":{path}")
        except subprocess.CalledProcessError:
            continue  # binary or unreadable
        for pat in SECRET_PATTERNS:
            if pat.search(content):
                problems.append(f"{path}: looks like a secret ({pat.pattern[:30]}...)")
        lowered = content.lower() + "\n" + path.lower()
        for term in terms:
            if term in lowered:
                problems.append(f"{path}: contains a denylisted partner term")

    if problems:
        print("Commit blocked by scripts/check_staged.py:")
        for p in problems:
            print("  -", p)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
