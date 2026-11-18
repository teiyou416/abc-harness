from __future__ import annotations

from pathlib import Path

import pytest

SMALL_PLAN = """\
title = "Small test plan"
question = "Does the harness run what was approved?"
simulator = "simblock"
rationale = "Test fixture."
seeds = [1, 2]
metrics = ["t90_ms", "orphan_rate"]
run_timeout_seconds = 5

[baseline]
NUM_OF_NODES = 10
END_BLOCK_HEIGHT = 3

[[configurations]]
name = "base"

[[configurations]]
name = "fast"
params = {{ INTERVAL = {interval} }}
"""


@pytest.fixture
def write_plan(tmp_path: Path):
    """Write the small test plan, optionally with a different INTERVAL, and return its path."""

    def _write(interval: int = 30000, name: str = "plan.toml") -> Path:
        path = tmp_path / name
        path.write_text(SMALL_PLAN.format(interval=interval), encoding="utf-8")
        return path

    return _write
