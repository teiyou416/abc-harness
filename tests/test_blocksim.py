from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from doubles.fake_runner import FakeRunner

from abc_harness.plan import validate_plan
from abc_harness.simulators import SimulatorError
from abc_harness.simulators.blocksim import CONFIG_FILE, MAIN_FILE, BlockSim
from abc_harness.task import run_task

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "blocksim"
BASE = {"simTime": 86400, "HASH_POWERS": [50, 20, 30]}


@pytest.fixture
def source(tmp_path: Path) -> Path:
    dest = tmp_path / "src"
    shutil.copytree(FIXTURES / "source", dest)
    return dest


def test_apply_params_edits_only_the_bitcoin_block(source):
    params = {"simTime": 3600, "HASH_POWERS": [70, 30], "Bdelay": 60, "Ttechnique": "Full", "hasTrans": False}
    changed = BlockSim().apply_params(source, params, seed=9)
    config = (source / CONFIG_FILE).read_text()
    assert changed == [CONFIG_FILE, MAIN_FILE]
    assert "    model = 1\n" in config
    assert "        Bdelay = 60  # average block propogation delay" in config
    assert "        NODES = [Node(id=0, hashPower=70), Node(id=1, hashPower=30)]" in config
    assert "        Nn = 2  # the total number of nodes" in config
    assert "        simTime = 3600  # the simulation length" in config
    assert "        Ttechnique = 'Full'  # Full/Light" in config
    assert "        hasTrans = False  # True/False" in config
    bitcoin = config.split("if model == 1:")[1].split("if model == 2:")[0]
    assert "        Runs = 1  # Number of simulation runs" in bitcoin
    # The base and Ethereum blocks keep their upstream values.
    assert "        Binterval = 600  # base model value that must stay untouched" in config
    assert "        Runs = 2  # Number of simulation runs" in config.split("if model == 1:")[0]
    assert "        Binterval = 12.42  # Ethereum value that must stay untouched" in config
    main = (source / MAIN_FILE).read_text()
    assert "    _abc_random.seed(9)\n    _abc_numpy.random.seed(9)\n    main()" in main


def test_apply_params_refuses_when_upstream_source_changed(source):
    config = source / CONFIG_FILE
    config.write_text(config.read_text().replace("        Bdelay = 0.42", "        BlockDelay = 0.42"))
    with pytest.raises(SimulatorError, match="exactly one Bdelay"):
        BlockSim().apply_params(source, {**BASE, "Bdelay": 1}, seed=1)


@pytest.mark.parametrize(
    "params",
    [
        {"simTime": 86400},
        {**BASE, "NUM_OF_NODES": 10},
        {**BASE, "HASH_POWERS": [100]},
        {**BASE, "HASH_POWERS": [50, 0]},
        {**BASE, "HASH_POWERS": [50, True]},
        {**BASE, "hasTrans": 1},
        {**BASE, "Ttechnique": "Medium"},
        {**BASE, "Bdelay": -1},
        {**BASE, "simTime": "86400"},
    ],
)
def test_invalid_params_are_refused(params):
    with pytest.raises(SimulatorError):
        BlockSim().validate_params(params)


def test_metrics_follow_their_definitions():
    # Fixture: 10 blocks, 2 stale; 8 main-chain blocks after genesis, 5 by node 0.
    assert BlockSim().compute_metrics(FIXTURES / "output", BASE) == {"stale_rate": 0.2, "node0_block_share": 0.625}


def test_recompute_script_agrees_on_blocksim_output():
    result = subprocess.run(
        [sys.executable, "-I", str(ROOT / "scripts" / "recompute_metric.py"), str(FIXTURES / "output")],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert json.loads(result.stdout) == {"stale_rate": 0.2, "node0_block_share": 0.625}


def test_example_plan_runs_in_the_blocksim_image(tmp_path):
    runner = FakeRunner()
    result = run_task(ROOT / "examples" / "blocksim-baseline.toml", runner, lambda p: ("approve", ""),
                      runs_root=tmp_path / "runs")  # fmt: skip
    assert result.status == "completed"
    assert set(runner.images) == {runner.image_info(BlockSim.image_tag)["image_id"]}
    assert len(runner.runs) == 10
    assert result.runs[0].metrics == {"stale_rate": 0.2, "node0_block_share": 0.625}
    assert (result.artifact_dir / "raw" / "delay-60s__seed-5" / "Chain.csv").exists()


def test_capability_card_lists_every_parameter():
    card = BlockSim().describe()
    for name in ("simTime", "HASH_POWERS", "Bdelay", "Ttechnique"):
        assert f"| {name} |" in card
    assert "BS-N2" in card and "Revision: BlockSim 603361d" in card


def test_plans_choose_between_simulators():
    simblock = {"NUM_OF_NODES": 10, "END_BLOCK_HEIGHT": 3}
    common = {"title": "t", "question": "q", "rationale": "r", "seeds": [1], "run_timeout_seconds": 10,
              "configurations": [{"name": "base"}]}  # fmt: skip
    validate_plan({**common, "simulator": "blocksim", "metrics": ["stale_rate"], "baseline": BASE})
    with pytest.raises(SimulatorError):
        validate_plan({**common, "simulator": "blocksim", "metrics": ["t90_ms"], "baseline": BASE})
    with pytest.raises(SimulatorError):
        validate_plan({**common, "simulator": "blocksim", "metrics": ["stale_rate"], "baseline": simblock})
