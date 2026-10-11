import pytest

from whetstone.adapter import Example, Score
from whetstone.objective import Constraint, Objective
from whetstone.split import HeldOutAccessError, Split
from whetstone.store import JsonlStore

EXAMPLES = [Example(id=f"ex{i:03d}", input=f"text {i}", expected=i % 3) for i in range(100)]


def test_split_is_deterministic_and_disjoint():
    a, b = Split.create(EXAMPLES, seed=7), Split.create(EXAMPLES, seed=7)
    assert a.split_hash == b.split_hash
    assert len(a.train_ids) + len(a.val_ids) + len(a.heldout_ids) == 100
    a.verify()


def test_split_roundtrip_and_tamper_detection(tmp_path):
    s = Split.create(EXAMPLES)
    s.save(tmp_path / "split.json")
    assert Split.load(tmp_path / "split.json").heldout_hash == s.heldout_hash
    s.heldout_ids[0] = "ex999"
    with pytest.raises(ValueError):
        s.verify()


def test_heldout_guard():
    s = Split.create(EXAMPLES)
    with pytest.raises(HeldOutAccessError):
        s.heldout(EXAMPLES)
    assert len(s.heldout(EXAMPLES, final_eval=True)) == len(s.heldout_ids)
    with pytest.raises(AssertionError):
        s.assert_not_heldout(EXAMPLES)
    s.assert_not_heldout(s.train(EXAMPLES) + s.val(EXAMPLES))


def test_objective_with_baseline_constraint():
    base = Objective.aggregate([Score({"success": 1, "tokens": 1000}), Score({"success": 1, "tokens": 1000})])
    cheaper_ok = Objective.aggregate([Score({"success": 1, "tokens": 500}), Score({"success": 1, "tokens": 500})])
    cheaper_bad = Objective.aggregate([Score({"success": 0, "tokens": 100}), Score({"success": 1, "tokens": 100})])
    obj = Objective("tokens", "min", [Constraint("success", ">=", -0.02, relative_to_baseline=True)])
    assert obj.fitness(cheaper_ok, base) > obj.fitness(base, base) > obj.fitness(cheaper_bad, base)


def test_jsonl_store(tmp_path):
    st = JsonlStore(tmp_path)
    assert st.insert("rounds", {"run_id": "r1", "round": 0, "best": 0.5}) == 0
    assert st.insert("rounds", {"run_id": "r1", "round": 1, "best": 0.7}) == 1
    assert JsonlStore(tmp_path).insert("rounds", {"run_id": "r1", "round": 2, "best": 0.8}) == 2  # survives restart
    assert [d["best"] for d in st.find("rounds", run_id="r1")] == [0.5, 0.7, 0.8]
    assert st.find("rounds", run_id="r1", round=1)[0]["best"] == 0.7


def test_bootstrap_ci():
    from whetstone.final_eval import bootstrap_ci
    assert bootstrap_ci([1.0] * 30) == (1.0, 1.0)
    lo, hi = bootstrap_ci([0.0] * 50 + [1.0] * 50, n=2000)
    assert 0.38 < lo < 0.5 < hi < 0.62


def test_predefined_split():
    s = Split.from_ids(["a", "b"], ["c"], ["d", "e"])
    s.verify()
    assert s.seed == -1 and s.heldout(EXAMPLES[:0] + [Example("d", 1), Example("e", 2)], final_eval=True)
    with pytest.raises(ValueError):
        Split.from_ids(["a"], ["b"], ["a"])
