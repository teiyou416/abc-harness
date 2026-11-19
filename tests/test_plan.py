from __future__ import annotations

from pathlib import Path

import pytest

from abc_harness.planning.plan import PlanError, load_plan, validate_plan
from abc_harness.simulators import SimulatorError

ROOT = Path(__file__).resolve().parents[1]


def test_example_plan_expands_to_configurations_times_seeds():
    plan = load_plan(ROOT / "examples" / "simblock-baseline.toml")
    runs = plan.runs()
    assert len(runs) == 10
    assert runs[0].run_id == "interval-600s__seed-1"
    assert runs[-1].run_id == "interval-30s__seed-5"
    assert runs[-1].params == {"NUM_OF_NODES": 300, "END_BLOCK_HEIGHT": 100, "INTERVAL": 30000}


def test_version_is_stable_and_changes_with_any_parameter(write_plan):
    first = load_plan(write_plan(interval=30000, name="a.toml"))
    again = load_plan(write_plan(interval=30000, name="b.toml"))
    changed = load_plan(write_plan(interval=60000, name="c.toml"))
    assert first.version == again.version
    assert first.version != changed.version


def _plan_data(**overrides):
    data = {
        "title": "t",
        "question": "q",
        "simulator": "simblock",
        "rationale": "r",
        "seeds": [1],
        "metrics": ["t90_ms"],
        "run_timeout_seconds": 10,
        "baseline": {"NUM_OF_NODES": 10, "END_BLOCK_HEIGHT": 3},
        "configurations": [{"name": "base"}],
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"extra": 1}, PlanError),
        ({"seeds": []}, PlanError),
        ({"seeds": [True]}, PlanError),
        ({"seeds": [1, 1]}, PlanError),
        ({"configurations": [{"name": "a b"}]}, PlanError),
        ({"permitted_edits": ["src/x.java"]}, PlanError),
        ({"simulator": "ethereum"}, SimulatorError),
        ({"metrics": ["throughput"]}, SimulatorError),
        ({"baseline": {"NUM_OF_NODES": 10}}, SimulatorError),
        ({"baseline": {"NUM_OF_NODES": 10, "END_BLOCK_HEIGHT": 3, "ALGO": "x"}}, SimulatorError),
        ({"baseline": {"NUM_OF_NODES": 1, "END_BLOCK_HEIGHT": 3}}, SimulatorError),
        ({"baseline": {"NUM_OF_NODES": 10, "END_BLOCK_HEIGHT": 3, "CBR_USAGE_RATE": 1.5}}, SimulatorError),
    ],
)
def test_invalid_plans_are_refused(overrides, error):
    with pytest.raises(error):
        validate_plan(_plan_data(**overrides))


def test_valid_plan_data_is_accepted():
    assert validate_plan(_plan_data()).runs()[0].run_id == "base__seed-1"


@pytest.mark.parametrize("image", ["abc-harness-sim:simblock-8a1285a", "sha256:short", "sha256:" + "G" * 64])
def test_execution_image_must_be_a_full_image_id(image, write_plan):
    data = load_plan(write_plan()).data
    with pytest.raises(PlanError, match="execution_image"):
        validate_plan({**data, "execution_image": image})
