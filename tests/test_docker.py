"""Integration tests against the real execution image. Run with `make test-docker`."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from abc_harness.execution.runner import DockerRunner, running_containers
from abc_harness.execution.task import new_task_id, run_task
from abc_harness.simulators.blocksim import BLOCKSIM_COMMIT, BlockSim
from abc_harness.simulators.simblock import SimBlock

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


def test_sandbox_source_is_read_only_and_scratch_is_writable(runner, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    source, scratch = tmp_path / "src", tmp_path / "scratch"
    source.mkdir()
    scratch.mkdir()
    (source / "code.py").write_text("print('original')\n")
    command = (
        "python -c 'print(1)' > /dev/null 2>&1; "  # the BlockSim image has Python; SimBlock's has a JDK
        "echo changed > /work/src/code.py && echo SOURCE-WRITABLE || echo SOURCE-READ-ONLY; "
        "echo test > /work/scratch/out.txt && echo SCRATCH-WRITABLE; "
        "cat /proc/net/route | wc -l; env | grep -c ANTHROPIC || true; pwd"
    )
    outcome = runner.sandbox(BlockSim.image_tag, new_task_id(), "sandbox-1", source, scratch, command, 60)
    lines = outcome.output.split()
    assert outcome.exit_code == 0, outcome.output
    assert "SOURCE-READ-ONLY" in lines and "SOURCE-WRITABLE" not in lines
    assert (source / "code.py").read_text() == "print('original')\n"
    assert "SCRATCH-WRITABLE" in lines and (scratch / "out.txt").read_text() == "test\n"
    assert lines[-3:] == ["1", "0", "/work/scratch"]  # route header only; no key; scratch is the working dir


def test_sandbox_timeout_removes_the_container(runner, tmp_path):
    task_id = new_task_id()
    (tmp_path / "s").mkdir()
    outcome = runner.sandbox(IMAGE, task_id, "sandbox-1", tmp_path / "s", tmp_path, "echo started; sleep 120", 3)
    assert outcome.timed_out
    assert running_containers(task_id) == []


@pytest.fixture(scope="module")
def pdf_runner() -> DockerRunner:
    from abc_harness.literature.pdf import PARSER_IMAGE

    runner = DockerRunner()
    try:
        runner.image_info(PARSER_IMAGE)
    except (RuntimeError, FileNotFoundError):
        pytest.skip("PDF parser image missing; run `uv run abc-harness image build --only pdf-parser`")
    return runner


def test_real_pdf_parser_reads_a_pdf_offline_and_is_cached(pdf_runner, tmp_path, monkeypatch):
    from abc_harness.execution.task import Task
    from abc_harness.literature import Library

    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    task = Task(pdf_runner, tmp_path / "runs")
    library = Library(task.artifact_dir, None, task.convert_pdf)
    pdf = ROOT / "tests" / "fixtures" / "pdf" / "handwritten.pdf"
    paper = library.shelve(pdf, "papers/handwritten.pdf")
    library.read(paper.id, time_left=900)
    assert paper.title == "A Tiny Paper About Selfish Mining"
    assert library.locate(paper.id, "Selfish mining lets a pool earn more than its fair share of the blocks.")
    assert task.pdf_parses[0]["revision"].startswith("mineru 4.2.3; models MinerU-4_models_onnx@")
    assert running_containers(task.task_id) == []
    log = (task.artifact_dir / "papers" / "local-handwritten" / "pdf" / "parser.log").read_text()
    assert SECRET not in log
    again = Task(pdf_runner, tmp_path / "runs")
    second = Library(again.artifact_dir, None, again.convert_pdf)
    second.read(second.shelve(pdf, "papers/handwritten.pdf").id, time_left=900)
    assert again.pdf_parses[0]["cached"] is True


def test_pdf_parser_timeout_removes_the_container(pdf_runner, tmp_path):
    from abc_harness.literature.pdf import PARSER_IMAGE

    task_id = new_task_id()
    image = pdf_runner.image_info(PARSER_IMAGE)["image_id"]
    out = tmp_path / "out"
    out.mkdir()
    outcome = pdf_runner.convert_pdf(image, task_id, "pdf-1", ROOT / "tests" / "fixtures" / "pdf" / "handwritten.pdf",
                                     out, timeout_seconds=1)  # fmt: skip
    assert outcome.timed_out
    assert running_containers(task_id) == []


@pytest.fixture(scope="module")
def plot_runner() -> DockerRunner:
    from abc_harness.execution.figures import PLOT_IMAGE

    runner = DockerRunner()
    try:
        runner.image_info(PLOT_IMAGE)
    except (RuntimeError, FileNotFoundError):
        pytest.skip("plot image missing; run `uv run abc-harness image build --only plot`")
    return runner


def _task_with_results(runner, tmp_path):
    from abc_harness.execution.task import RunRecord, Task

    task = Task(runner, tmp_path / "runs")
    plan = {"configurations": [{"name": "base"}, {"name": "slow", "params": {"delay": 60}}], "baseline": {"delay": 1},
            "metrics": ["stale_rate"]}  # fmt: skip
    (task.artifact_dir / "plan.json").write_text(json.dumps(plan))
    task.records = [RunRecord(f"{c}__seed-{s}", c, s, {}, status="completed", metrics={"stale_rate": v})
                    for c, s, v in [("base", 1, 0.01), ("base", 2, 0.012), ("slow", 1, 0.05), ("slow", 2, 0.058)]]  # fmt: skip
    return task


def test_real_plot_image_draws_from_the_results(plot_runner, tmp_path):
    from abc_harness.execution.figures import draw
    from abc_harness.literature.figures import image_size

    script = """import abcplot
abcplot.use_style()
stats = abcplot.summary("stale_rate")
print(stats)
fig, ax = abcplot.figure()
names = list(stats)
ax.errorbar(range(len(names)), [stats[n][0] for n in names], yerr=[stats[n][1] for n in names], fmt="o")
ax.set_xticks(range(len(names)), names)
ax.set_ylabel("Stale rate (fraction of blocks)")
abcplot.save(fig)
"""
    task = _task_with_results(plot_runner, tmp_path)
    drawn = draw(task, "stale-rate", script, "Stale rate; mean ± sd over 2 seeds.")
    assert "'base': (0.011" in drawn.output and "'slow': (0.054" in drawn.output and "2)" in drawn.output
    width, _ = image_size(drawn.png_bytes)
    assert 600 <= width <= 700  # 3.25 in at 200 dpi, tight bounding box
    assert (task.artifact_dir / "figures" / "stale-rate.svg").read_text().startswith("<?xml")
    assert running_containers(task.task_id) == []


def test_plot_scripts_cannot_write_data_or_reach_the_network(plot_runner, tmp_path, monkeypatch):
    from abc_harness.execution.figures import FigureError, draw

    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    script = """import os, socket
assert "ANTHROPIC_API_KEY" not in os.environ
try:
    open("/data/results.json", "w")
    raise SystemExit("data was writable")
except OSError:
    pass
try:
    socket.create_connection(("1.1.1.1", 53), timeout=2)
    raise SystemExit("network reachable")
except OSError:
    pass
print("sealed")
"""
    task = _task_with_results(plot_runner, tmp_path)
    with pytest.raises(FigureError, match="wrote no /out/figure.png"):
        draw(task, "probe", script, "probe")
    assert (task.artifact_dir / "figures" / "probe.log").read_text().strip() == "sealed"
