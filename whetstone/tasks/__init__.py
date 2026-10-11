"""Task registry. Each task is a TaskAdapter plus where its frozen split lives."""
from __future__ import annotations

from pathlib import Path

from ..adapter import TaskAdapter
from ..split import Split


def get_task(name: str) -> TaskAdapter:
    if name == "classify":
        from .classify import ClassifyAdapter
        return ClassifyAdapter()
    if name == "codefix":
        from .codefix import CodeFixAdapter
        return CodeFixAdapter()
    raise KeyError(f"unknown task {name!r}")


def split_path(name: str) -> Path:
    return Path("data") / name / "split.json"


def load_or_create_split(name: str, adapter: TaskAdapter, seed: int = 42) -> tuple[Split, bool]:
    """Returns (split, created). Once created, the split is frozen: always loaded + hash-verified."""
    p = split_path(name)
    if p.exists():
        return Split.load(p), False
    s = Split.create(adapter.examples(), seed=seed)
    s.save(p)
    return s, True
