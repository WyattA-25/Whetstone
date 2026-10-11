"""Frozen train / validation / held-out split with a hash.

The hash is recorded when the split is created and verified before final evaluation,
so we can prove the held-out set never changed. The held-out examples can only be
read through `heldout(final_eval=True)`; the optimizer loop never passes that flag.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path

from .adapter import Example


class HeldOutAccessError(RuntimeError):
    pass


def _hash_ids(ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()


@dataclass
class Split:
    train_ids: list[str]
    val_ids: list[str]
    heldout_ids: list[str]
    seed: int
    heldout_hash: str
    split_hash: str

    @classmethod
    def create(cls, examples: list[Example], seed: int = 42,
               ratios: tuple[float, float, float] = (0.5, 0.2, 0.3)) -> "Split":
        ids = sorted(e.id for e in examples)
        if len(set(ids)) != len(ids):
            raise ValueError("example ids must be unique")
        random.Random(seed).shuffle(ids)
        n_tr, n_va = int(len(ids) * ratios[0]), int(len(ids) * ratios[1])
        tr, va, ho = ids[:n_tr], ids[n_tr:n_tr + n_va], ids[n_tr + n_va:]
        return cls(tr, va, ho, seed, _hash_ids(ho),
                   _hash_ids([f"train:{i}" for i in tr] + [f"val:{i}" for i in va] + [f"heldout:{i}" for i in ho]))

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.__dict__, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "Split":
        s = cls(**json.loads(Path(path).read_text()))
        s.verify()
        return s

    def verify(self) -> None:
        if _hash_ids(self.heldout_ids) != self.heldout_hash:
            raise ValueError("held-out set changed since the split was frozen")
        overlap = (set(self.train_ids) | set(self.val_ids)) & set(self.heldout_ids)
        if overlap:
            raise ValueError(f"held-out ids leaked into train/val: {sorted(overlap)[:5]}")

    def _pick(self, examples: list[Example], ids: list[str]) -> list[Example]:
        by_id = {e.id: e for e in examples}
        missing = [i for i in ids if i not in by_id]
        if missing:
            raise ValueError(f"examples missing from dataset: {missing[:5]}")
        return [by_id[i] for i in ids]

    def train(self, examples: list[Example]) -> list[Example]:
        return self._pick(examples, self.train_ids)

    def val(self, examples: list[Example]) -> list[Example]:
        return self._pick(examples, self.val_ids)

    def heldout(self, examples: list[Example], *, final_eval: bool = False) -> list[Example]:
        if not final_eval:
            raise HeldOutAccessError("held-out examples are only available to the final evaluation")
        self.verify()
        return self._pick(examples, self.heldout_ids)

    def assert_not_heldout(self, examples: list[Example]) -> None:
        """Called by the loop on every batch it scores, selects on, or shows to the analyst."""
        leaked = {e.id for e in examples} & set(self.heldout_ids)
        assert not leaked, f"held-out examples used during optimization: {sorted(leaked)[:5]}"
