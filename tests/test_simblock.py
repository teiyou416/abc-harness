from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from abc_harness.simulators import SimulatorError
from abc_harness.simulators.simblock import CONFIG_FILE, MAIN_FILE, SimBlock

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "simblock"


@pytest.fixture
def source(tmp_path: Path) -> Path:
    dest = tmp_path / "src"
    shutil.copytree(FIXTURES / "source", dest)
    return dest


def test_apply_params_writes_constants_and_seed(source):
    changed = SimBlock().apply_params(
        source, {"NUM_OF_NODES": 10, "END_BLOCK_HEIGHT": 50, "INTERVAL": 30000, "CBR_USAGE_RATE": 0.5}, seed=7
    )
    config = (source / CONFIG_FILE).read_text()
    assert changed == [CONFIG_FILE, MAIN_FILE]
    assert "public static final int NUM_OF_NODES = 10; // 600;//800;//6000;" in config
    assert "public static final long INTERVAL = 30000L;" in config
    assert "public static final int END_BLOCK_HEIGHT = 50;" in config
    assert "public static final float CBR_USAGE_RATE = 0.5f;" in config
    # Commented-out duplicates stay untouched.
    assert "// public static final int END_BLOCK_HEIGHT = 100;" in config
    assert "// public static final int NUM_OF_NODES = 600;" in config
    assert "new Random(7L);" in (source / MAIN_FILE).read_text()


def test_apply_params_refuses_when_upstream_source_changed(source):
    config = source / CONFIG_FILE
    config.write_text(config.read_text().replace("public static final long INTERVAL", "public static long INTERVAL"))
    with pytest.raises(SimulatorError, match="exactly one INTERVAL"):
        SimBlock().apply_params(source, {"NUM_OF_NODES": 10, "END_BLOCK_HEIGHT": 3, "INTERVAL": 1}, seed=1)


def test_metrics_follow_their_definitions():
    # Fixture: 10 nodes, so a block needs 9 receptions. Block 0 reaches its
    # 9th node at 80 ms and block 1 at 800 ms; block 2 reached only 5 nodes and
    # is skipped. blockList.txt has 1 orphan among 4 lines.
    metrics = SimBlock().compute_metrics(FIXTURES, {"NUM_OF_NODES": 10})
    assert metrics == {"t90_ms": 440.0, "orphan_rate": 0.25}


def test_recompute_script_agrees_with_harness_without_importing_it():
    script = ROOT / "scripts" / "recompute_metric.py"
    result = subprocess.run(
        [sys.executable, "-I", str(script), str(FIXTURES), "--nodes", "10"],
        capture_output=True, text=True, check=True,
    )  # fmt: skip
    assert json.loads(result.stdout) == {"t90_ms": 440.0, "orphan_rate": 0.25}
