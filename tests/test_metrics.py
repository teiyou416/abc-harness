"""Metrics: built-in metrics are computed only when the plan asks for them; custom metrics come from the
`ABC_METRIC <name>=<value>` lines that agent-written code prints."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from doubles.fake_runner import FakeRunner
from test_edits import STRATEGY, coding_steps, edit_plan, run

from abc_harness.planning.plan import PlanError, validate_plan
from abc_harness.simulators.base import SimulatorError, read_custom_metrics
from abc_harness.simulators.simblock import SimBlock

ROOT = Path(__file__).resolve().parents[1]
SIMBLOCK = ROOT / "tests" / "fixtures" / "simblock"
SHARE = {"name": "pool_share", "definition": "blocks the pool mined on the final main chain / main-chain blocks"}


def custom_plan(**overrides):
    plan = edit_plan(metrics=["stale_rate", "pool_share"], custom_metrics=[SHARE],
                     validation={"description": "honest pool earns its hash share", "params": {}, "seeds": [7],
                                 "metric": "pool_share", "expected": 0.30, "tolerance": 0.01})  # fmt: skip
    plan.update(overrides)
    return plan


def prints_share(run_id, workdir):
    return "ABC_METRIC pool_share=0.25\nsome log line\nABC_METRIC pool_share=0.301\n"


# ----- built-in metrics on request -----


def test_a_metric_not_asked_for_is_not_computed(tmp_path):
    """The bug behind a failed task: no propagation log made every run fail, though only orphan_rate was asked."""
    shutil.copyfile(SIMBLOCK / "blockList.txt", tmp_path / "blockList.txt")
    (tmp_path / "stdout.txt").write_text("the edited model printed no propagation log\n")
    params = {"NUM_OF_NODES": 10}
    assert set(SimBlock().compute_metrics(tmp_path, params, ["orphan_rate"])) == {"orphan_rate"}
    with pytest.raises(SimulatorError, match="t90_ms is undefined"):
        SimBlock().compute_metrics(tmp_path, params, ["t90_ms"])


def test_the_recompute_script_reports_each_metric_on_its_own(tmp_path):
    shutil.copyfile(SIMBLOCK / "blockList.txt", tmp_path / "blockList.txt")
    (tmp_path / "stdout.txt").write_text("no propagation log\nABC_METRIC pool_share=0.301\n")
    out = subprocess.run([sys.executable, "-I", str(ROOT / "scripts" / "recompute_metric.py"), str(tmp_path),
                          "--nodes", "10"], capture_output=True, text=True, check=True)  # fmt: skip
    result = json.loads(out.stdout)
    assert isinstance(result["orphan_rate"], float) and result["t90_ms"].startswith("not computable")
    assert result["pool_share"] == 0.301


# ----- reading custom metrics -----


def test_custom_metrics_take_the_last_line_per_name(tmp_path):
    stdout = tmp_path / "stdout.txt"
    stdout.write_text(prints_share("r", tmp_path) + "ABC_METRIC other=2\n")
    assert read_custom_metrics(stdout, ["pool_share", "other"]) == {"pool_share": 0.301, "other": 2.0}


@pytest.mark.parametrize(("text", "message"), [
    ("nothing\n", "printed no 'ABC_METRIC pool_share=<value>' line"),
    ("ABC_METRIC pool_share=high\n", "is not a number"),
    ("ABC_METRIC pool_share=nan\n", "is not finite"),
])  # fmt: skip
def test_missing_or_bad_custom_metrics_fail_the_run(tmp_path, text, message):
    (tmp_path / "stdout.txt").write_text(text)
    with pytest.raises(SimulatorError, match=message):
        read_custom_metrics(tmp_path / "stdout.txt", ["pool_share"])


# ----- declaring custom metrics in a plan -----


@pytest.mark.parametrize(("change", "message"), [
    ({"custom_metrics": [{**SHARE, "name": "stale_rate"}], "metrics": ["stale_rate"]},
     "stale_rate is a built-in metric of blocksim"),
    ({"custom_metrics": [{**SHARE, "name": "Pool Share"}]}, "lowercase letters"),
    ({"custom_metrics": [{"name": "pool_share"}]}, "exactly a name and a definition"),
    ({"metrics": ["stale_rate"], "validation": {**edit_plan()["validation"], "metric": "stale_rate"}},
     "must also be listed in metrics"),
    ({"custom_metrics": [SHARE, SHARE]}, "unique"),
    ({"metrics": ["pool_share"]}, "honest run the original source, which cannot print custom metrics"),
])  # fmt: skip
def test_custom_metric_declarations_are_checked(change, message):
    with pytest.raises(PlanError, match=message):
        validate_plan(custom_plan(**change))


def test_custom_metrics_need_permitted_edits():
    plan = custom_plan(configurations=[{"name": "a"}])
    del plan["permitted_edits"], plan["validation"]
    with pytest.raises(PlanError, match="custom metrics need permitted edits"):
        validate_plan(plan)


def test_the_review_shows_custom_metrics_with_their_definitions():
    text = validate_plan(custom_plan()).render()
    assert "Custom metrics (defined by this plan; the edited source prints `ABC_METRIC <name>=<value>`" in text
    assert f"  pool_share: {SHARE['definition']}" in text


# ----- end to end -----


def test_custom_metrics_flow_into_validation_results_and_the_report(tmp_path):
    runner = FakeRunner(stdout_extra=prints_share)
    result, _, _ = run(coding_steps(custom_plan()), tmp_path, runner=runner)
    assert result.status == "completed", result.stop_reason
    validation = json.loads((result.artifact_dir / "validation.json").read_text())
    assert validation["passed"] and validation["mean"] == 0.301

    by_config = {}
    for r in json.loads((result.artifact_dir / "results.json").read_text()):
        by_config.setdefault(r["configuration"], []).append(r["metrics"])
    assert all(m == {"stale_rate": 0.2, "pool_share": 0.301} for m in by_config["selfish"])
    assert all(m == {"stale_rate": 0.2} for m in by_config["honest"])  # original source: built-in metrics only

    report = (result.artifact_dir / "report.md").read_text()
    assert "Custom metrics, defined by this plan and computed by the agent-written code" in report
    assert f"- `pool_share`: {SHARE['definition']}" in report
    assert "| honest | 0.2000 ± 0.0000 (n=2) | no data |" in report


def test_edited_code_that_forgets_the_line_fails_validation_with_the_reason(tmp_path):
    result, _, _ = run(coding_steps(custom_plan()), tmp_path, runner=FakeRunner())
    assert result.status == "failed" and "only 0 of 1 validation runs completed" in result.stop_reason
    validation = json.loads((result.artifact_dir / "validation.json").read_text())
    assert "printed no 'ABC_METRIC pool_share=<value>' line" in validation["runs"][0]["error"]
    assert STRATEGY in (result.artifact_dir / "changes" / "edits.diff").read_text()
