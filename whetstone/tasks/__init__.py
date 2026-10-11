"""Task registry. Each task is a TaskAdapter plus where its frozen split lives."""
from __future__ import annotations

from pathlib import Path

from ..adapter import TaskAdapter
from ..split import Split


def get_task(name: str) -> TaskAdapter:
    if name == "classify":
        from .classify import ClassifyAdapter
        return ClassifyAdapter()
    if name == "banking77":
        from .classify import Banking77Adapter
        return Banking77Adapter()
    if name.startswith("pilot"):
        # Confidential pilots: the adapter lives in the git-ignored pilot/ folder and is never committed.
        import importlib.util
        path = PRIVATE_DIR / f"{name}.py"
        if not path.exists():
            raise KeyError(f"private task {name!r} not found at {path}")
        spec = importlib.util.spec_from_file_location(f"private_{name}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.Adapter()
    if name == "codefix":
        from .codefix import CodeFixAdapter
        return CodeFixAdapter()
    raise KeyError(f"unknown task {name!r}")


PRIVATE_DIR = Path("pilot")


def is_private(name: str) -> bool:
    return name.startswith("pilot")


def split_path(name: str) -> Path:
    return (PRIVATE_DIR / "data" / name if is_private(name) else Path("data") / name) / "split.json"


def load_or_create_split(name: str, adapter: TaskAdapter, seed: int = 42) -> tuple[Split, bool]:
    """Returns (split, created). Once created, the split is frozen: always loaded + hash-verified."""
    p = split_path(name)
    if p.exists():
        return Split.load(p), False
    fixed = adapter.split_assignment()
    s = Split.from_ids(fixed["train"], fixed["val"], fixed["heldout"]) if fixed else Split.create(adapter.examples(), seed=seed)
    s.save(p)
    return s, True
