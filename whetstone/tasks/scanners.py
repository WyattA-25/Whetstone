"""Scanner plumbing for the code-fix adapter: run a scanner, normalize its findings.

Every scanner is reduced to the same Finding shape, so adding one (Trivy, Semgrep, any SARIF
producer) means adding one parser here. The optimizer core never sees any of this.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

# Correctness / security / simplification / performance families. Pure style rules
# (docstrings, annotations, quotes, line length) are excluded on purpose.
RUFF_SELECT = "E,F,B,S,SIM,C4,PERF,PL,RUF,UP"
# Also excluded: intentional re-exports (PLC0414), API-changing (PLR0913/0917), multi-function
# refactors (PLR0911/0912/0915), and noisy magic-number warnings (PLR2004).
RUFF_IGNORE = "E501,PLC0414,PLR0913,PLR0917,PLR0911,PLR0912,PLR0915,PLR2004"


@dataclass(frozen=True)
class Finding:
    tool: str
    rule: str
    message: str
    path: str            # relative to repo root, forward slashes
    line: int
    end_line: int

    def as_dict(self) -> dict:
        return asdict(self)


def _rel(path: str, root: Path) -> str:
    p = Path(path)
    try:
        p = p.resolve().relative_to(root.resolve())
    except ValueError:
        pass
    return p.as_posix()


def _tool(name: str) -> list[str]:
    """Run scanners from our own venv, never the scanned repo's."""
    return [sys.executable, "-m", name]


def ruff(root: Path, target: str, timeout: int = 120) -> list[Finding]:
    r = subprocess.run(_tool("ruff") + ["check", "--select", RUFF_SELECT, "--ignore", RUFF_IGNORE,
                                        "--output-format", "json", "--exit-zero", "--no-cache", target],
                       cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    out = []
    for d in json.loads(r.stdout or "[]"):
        out.append(Finding("ruff", d["code"] or "syntax", d["message"], _rel(d["filename"], root),
                           d["location"]["row"], d["end_location"]["row"]))
    return out


def bandit(root: Path, target: str, timeout: int = 120) -> list[Finding]:
    r = subprocess.run(_tool("bandit") + ["-r", target, "-f", "json", "-q", "--exit-zero"],
                       cwd=root, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    data = json.loads(r.stdout or "{}")
    return [Finding("bandit", d["test_id"], d["issue_text"], _rel(d["filename"], root),
                    d["line_number"], max(d.get("line_range") or [d["line_number"]]))
            for d in data.get("results", [])]


def sarif(path: Path, root: Path, tool: str = "sarif") -> list[Finding]:
    """Generic SARIF reader (Trivy, Semgrep, CodeQL, SonarQube export...)."""
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for run in data.get("runs", []):
        name = run.get("tool", {}).get("driver", {}).get("name", tool).lower()
        for res in run.get("results", []):
            loc = (res.get("locations") or [{}])[0].get("physicalLocation", {})
            region = loc.get("region", {})
            uri = loc.get("artifactLocation", {}).get("uri", "")
            out.append(Finding(name, res.get("ruleId", "?"), res.get("message", {}).get("text", ""),
                               _rel(uri, root), region.get("startLine", 0),
                               region.get("endLine", region.get("startLine", 0))))
    return out


SCANNERS = {"ruff": ruff, "bandit": bandit}


def scan(tool: str, root: Path, target: str) -> list[Finding]:
    return SCANNERS[tool](root, target)
