"""Integration tests against the real execution image. Run with `make test-docker`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from abc_harness.runner import DockerRunner, running_containers
from abc_harness.simulators.blocksim import BLOCKSIM_COMMIT, BlockSim
from abc_harness.simulators.simblock import SimBlock
from abc_harness.task import new_task_id, run_task

pytestmark = pytest.mark.docker
ROOT = Path(__file__).resolve().parents[1]
SECRET = "sk-ant-test-secret-that-must-not-leak"


IMAGE = SimBlock.image_tag


@pytest.fixture(scope="module")
def runner() -> DockerRunner:
    runner = DockerRunner()
    try:
        runner.image_info(SimBlock.image_tag)
        runner.image_info(BlockSim.image_tag)
    except (RuntimeError, FileNotFoundError):
        pytest.skip("execution images missing; run `uv run abc-harness image build`")
    return runner


def test_container_receives_no_host_environment(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    outcome = runner.run(IMAGE, new_task_id(), "env", tmp_path, "env > env.txt", timeout_seconds=60)
    env = (tmp_path / "env.txt").read_text()
    assert outcome.exit_code == 0
    assert SECRET not in env
    assert "ANTHROPIC_API_KEY" not in env


def test_container_has_no_network_route(runner, tmp_path):
    outcome = runner.run(IMAGE, new_task_id(), "net", tmp_path, "cat /proc/net/route > routes.txt", timeout_seconds=60)
    routes = (tmp_path / "routes.txt").read_text().splitlines()
    assert outcome.exit_code == 0
    assert len(routes) == 1, routes  # header line only: no interface can reach anything


def test_timeout_removes_the_container(runner, tmp_path):
    task_id = new_task_id()
    outcome = runner.run(IMAGE, task_id, "sleep", tmp_path, "sleep 120", timeout_seconds=3)
    assert outcome.timed_out
    assert running_containers(task_id) == []


def test_real_simblock_run_matches_independent_recalculation(runner, tmp_path):
    plan = tmp_path / "plan.toml"
    plan.write_text(
        """
title = "Docker integration"
question = "Does a tiny real SimBlock run complete?"
simulator = "simblock"
rationale = "Integration test."
seeds = [3]
metrics = ["t90_ms", "orphan_rate"]
run_timeout_seconds = 120

[baseline]
NUM_OF_NODES = 50
END_BLOCK_HEIGHT = 5
INTERVAL = 60000

[[configurations]]
name = "tiny"
""",
        encoding="utf-8",
    )
    assert os.environ.get("ANTHROPIC_API_KEY") != SECRET
    result = run_task(plan, runner, lambda p: ("approve", ""), runs_root=tmp_path / "runs")
    assert result.status == "completed", result.stop_reason
    raw = result.artifact_dir / "raw" / "tiny__seed-3"
    recomputed = subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts" / "recompute_metric.py"), str(raw), "--nodes", "50"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert json.loads(recomputed.stdout) == result.runs[0].metrics
    manifest = json.loads((result.artifact_dir / "manifest.json").read_text())
    assert manifest["simulator_revision"] == "8a1285aa37b832385b0be2ae6f804885a4a7031f"
    assert running_containers(result.task_id) == []


def test_real_blocksim_run_matches_independent_recalculation(runner, tmp_path):
    plan = tmp_path / "plan.toml"
    plan.write_text(
        """
title = "BlockSim integration"
question = "Does a tiny real BlockSim run complete?"
simulator = "blocksim"
rationale = "Integration test."
seeds = [4]
metrics = ["stale_rate", "node0_block_share"]
run_timeout_seconds = 120

[baseline]
simTime = 20000
HASH_POWERS = [60, 40]
Bdelay = 30

[[configurations]]
name = "tiny"
""",
        encoding="utf-8",
    )
    result = run_task(plan, runner, lambda p: ("approve", ""), runs_root=tmp_path / "runs")
    assert result.status == "completed", result.stop_reason
    raw = result.artifact_dir / "raw" / "tiny__seed-4"
    recomputed = subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts" / "recompute_metric.py"), str(raw)],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert json.loads(recomputed.stdout) == result.runs[0].metrics
    manifest = json.loads((result.artifact_dir / "manifest.json").read_text())
    assert manifest["simulator_revision"] == BLOCKSIM_COMMIT
    assert manifest["image"] == BlockSim.image_tag
    pinned = json.loads((result.artifact_dir / "plan.json").read_text())["execution_image"]
    assert manifest["image_id"] == pinned == runner.image_info(BlockSim.image_tag)["image_id"]
    assert running_containers(result.task_id) == []
