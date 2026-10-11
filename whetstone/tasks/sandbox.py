"""Throwaway working copies and subprocess helpers for running untrusted model-written code.

Model fixes are untrusted: they only ever run inside a copy under .cache/sandboxes/, with a timeout
(and a memory cap on POSIX), and the copy is deleted afterwards. The original clone is never modified.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache"
SANDBOXES = CACHE / "sandboxes"
MEMORY_CAP_BYTES = 2 * 1024**3
_IGNORE = shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache", ".tox", ".nox", ".venv", "*.egg-info")


def repo_dir(name: str) -> Path:
    return CACHE / "repos" / name


def venv_dir(name: str) -> Path:
    return CACHE / "venvs" / name


def venv_bin(venv: Path) -> Path:
    return venv / ("Scripts" if os.name == "nt" else "bin")


def venv_env(venv: Path, extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env["PATH"] = str(venv_bin(venv)) + os.pathsep + env["PATH"]
    env["VIRTUAL_ENV"] = str(venv)
    env.pop("PYTHONHOME", None)
    # Never leak our secrets into code we didn't write.
    for k in list(env):
        if any(s in k.upper() for s in ("API_KEY", "SECRET", "TOKEN", "MONGODB", "AWS_", "STRIPE")):
            env.pop(k)
    # ...and point the AWS SDK away from our credential files so sandboxed code can't use them.
    env["AWS_SHARED_CREDENTIALS_FILE"] = env["AWS_CONFIG_FILE"] = os.devnull
    env.update(extra or {})
    return env


def _limit_memory():  # POSIX only; Windows has no setrlimit (documented limitation)
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_CAP_BYTES, MEMORY_CAP_BYTES))


def sh(cmd: str | list[str], cwd: Path, timeout: int = 600, env: dict | None = None) -> subprocess.CompletedProcess:
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    if env and "VIRTUAL_ENV" in env:  # Windows ignores env PATH when locating the program itself
        exe = venv_bin(Path(env["VIRTUAL_ENV"])) / (cmd[0] + (".exe" if os.name == "nt" else ""))
        if exe.exists():
            cmd = [str(exe), *cmd[1:]]
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, env=env, preexec_fn=_limit_memory if os.name != "nt" else None)


@contextmanager
def working_copy(name: str):
    """A fresh copy of the pristine clone, deleted on exit."""
    SANDBOXES.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=SANDBOXES))
    dst = tmp / name
    try:
        shutil.copytree(repo_dir(name), dst, ignore=_IGNORE)
        yield dst
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
