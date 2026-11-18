"""Task orchestration with FakeRunner: approval gate, statuses, limits, artifacts."""

from __future__ import annotations

import json
import subprocess

import pytest
from doubles.fake_runner import FakeClock, FakeRunner

from abc_harness import cli
from abc_harness.approval import NotApproved, read_decisions, require_approval
from abc_harness.limits import Budget
from abc_harness.plan import load_plan
from abc_harness.task import run_task
from abc_harness.trace import read_trace


def approve(plan):
    return "approve", ""


def reject(plan):
    return "reject", "not convinced"


def test_rejecting_starts_nothing(write_plan, tmp_path):
    runner = FakeRunner()
    result = run_task(write_plan(), runner, reject, runs_root=tmp_path / "runs")
    assert result.status == "rejected"
    assert runner.runs == [] and runner.exports == []
    assert not (result.artifact_dir / "workspace").exists()
    assert read_decisions(result.artifact_dir)[0].decision == "reject"
    assert all(r.status == "missing" for r in result.runs)
    assert (result.artifact_dir / "report.md").exists()


def test_approving_runs_every_planned_run_and_writes_artifacts(write_plan, tmp_path):
    runner = FakeRunner()
    result = run_task(write_plan(), runner, approve, runs_root=tmp_path / "runs")
    d = result.artifact_dir
    assert result.status == "completed"
    assert runner.runs == ["base__seed-1", "base__seed-2", "fast__seed-1", "fast__seed-2"]
    assert runner.cleanups == [result.task_id]
    assert result.runs[0].metrics == {"t90_ms": 440.0, "orphan_rate": 0.25}
    assert (d / "raw" / "fast__seed-2" / "stdout.txt").exists()
    assert "+  public static Random random = new Random(2L);" in (d / "changes" / "fast__seed-2.diff").read_text()
    manifest = json.loads((d / "manifest.json").read_text())
    assert manifest["simulator_revision"] == "fixture-revision"
    assert manifest["test_double"] is True
    assert "test double" in (d / "report.md").read_text()
    assert read_trace(d / "trace.jsonl")[-1]["event"] == "task_finished"


def test_approval_covers_only_the_approved_version(write_plan, tmp_path):
    result = run_task(write_plan(interval=30000, name="v1.toml"), FakeRunner(), approve, runs_root=tmp_path / "runs")
    v1 = load_plan(write_plan(interval=30000, name="v1.toml")).version
    v2 = load_plan(write_plan(interval=60000, name="v2.toml")).version
    require_approval(result.artifact_dir, v1)
    with pytest.raises(NotApproved):
        require_approval(result.artifact_dir, v2)


def test_failed_and_unparsable_runs_make_a_partial_task(write_plan, tmp_path):
    runner = FakeRunner(behaviours={"base__seed-1": "fail", "fast__seed-1": "garbage"})
    result = run_task(write_plan(), runner, approve, runs_root=tmp_path / "runs")
    statuses = {r.run_id: r.status for r in result.runs}
    assert result.status == "partial"
    assert statuses == {"base__seed-1": "failed", "base__seed-2": "completed", "fast__seed-1": "failed",
                        "fast__seed-2": "completed"}  # fmt: skip
    report = (result.artifact_dir / "report.md").read_text()
    assert "base__seed-1 (failed)" in report


def test_time_limit_stops_the_task_and_reports_missing_runs(write_plan, tmp_path):
    clock = FakeClock()
    runner = FakeRunner(clock=clock, seconds_per_run=4)
    budget = Budget(time_limit_seconds=10, clock=clock)
    result = run_task(write_plan(), runner, approve, runs_root=tmp_path / "runs", budget=budget)
    statuses = [r.status for r in result.runs]
    assert result.status == "stopped_by_limit"
    assert statuses == ["completed", "completed", "timeout", "missing"]
    assert result.task_id in runner.cleanups
    events = [e["event"] for e in read_trace(result.artifact_dir / "trace.jsonl")]
    assert "limit_reached" in events
    assert "fast__seed-2 (missing)" in (result.artifact_dir / "report.md").read_text()


def test_time_spent_waiting_for_the_researcher_does_not_count(write_plan, tmp_path):
    clock = FakeClock()

    def slow_approve(plan):
        clock.advance(3600)
        return "approve", ""

    budget = Budget(time_limit_seconds=10, clock=clock)
    result = run_task(write_plan(), FakeRunner(clock=clock), slow_approve, runs_root=tmp_path / "runs", budget=budget)
    assert result.status == "completed"
    manifest = json.loads((result.artifact_dir / "manifest.json").read_text())
    assert manifest["waiting_seconds"] == 3600
    assert manifest["active_seconds"] == 4


def test_end_of_input_counts_as_rejection(write_plan):
    def closed(_prompt):
        raise EOFError

    decision, _ = cli.prompt_decision(load_plan(write_plan()), read=closed, write=lambda _s: None)
    assert decision == "reject"


def test_cli_rejection_never_calls_docker(write_plan, tmp_path, monkeypatch, capsys):
    def no_subprocess(*args, **kwargs):
        raise AssertionError(f"subprocess called: {args}")

    monkeypatch.setattr(subprocess, "run", no_subprocess)
    answers = iter(["reject", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    code = cli.main(["run", str(write_plan()), "--runs-dir", str(tmp_path / "runs")])
    out = capsys.readouterr().out
    assert code == 0
    assert "No simulator was started." in out
    assert "Artifacts: " in out
