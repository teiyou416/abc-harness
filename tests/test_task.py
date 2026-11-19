"""Task orchestration with FakeRunner: approval gate, statuses, limits, artifacts."""

from __future__ import annotations

import json
import subprocess

import pytest
from doubles.fake_runner import FakeClock, FakeRunner

from abc_harness import cli
from abc_harness import runner as runner_module
from abc_harness.approval import NotApproved, read_decisions, require_approval
from abc_harness.limits import Budget
from abc_harness.plan import Plan, load_plan
from abc_harness.runner import RunnerError
from abc_harness.simulators.simblock import SimBlock
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


def pinned(plan, runner):
    image_id = runner.image_info(SimBlock.image_tag)["image_id"]
    return Plan({**plan.data, "execution_image": image_id})


def test_approval_covers_only_the_approved_version(write_plan, tmp_path):
    runner = FakeRunner()
    result = run_task(write_plan(interval=30000, name="v1.toml"), runner, approve, runs_root=tmp_path / "runs")
    v1 = pinned(load_plan(write_plan(interval=30000, name="v1.toml")), runner).version
    v2 = pinned(load_plan(write_plan(interval=60000, name="v2.toml")), runner).version
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


@pytest.mark.parametrize("limited", [False, True])
def test_failed_cleanup_still_writes_results_and_report(write_plan, tmp_path, limited):
    clock = FakeClock()
    runner = FakeRunner(cleanup_error="Cannot connect to the Docker daemon", clock=clock, seconds_per_run=4)
    budget = Budget(time_limit_seconds=10 if limited else 1800, clock=clock)
    result = run_task(write_plan(), runner, approve, runs_root=tmp_path / "runs", budget=budget)
    d = result.artifact_dir
    assert result.status == ("stopped_by_limit" if limited else "completed")
    manifest = json.loads((d / "manifest.json").read_text())
    assert manifest["status"] == result.status
    assert "Cannot connect to the Docker daemon" in manifest["cleanup_error"]
    assert json.loads((d / "results.json").read_text())[0]["status"] == "completed"
    assert "Container cleanup failed" in (d / "report.md").read_text()
    events = [e["event"] for e in read_trace(d / "trace.jsonl")]
    assert "cleanup_failed" in events and events[-1] == "task_finished"


def test_docker_cleanup_raises_when_the_daemon_is_unreachable(monkeypatch):
    def fake_docker(*args, check=True, timeout=None):
        return subprocess.CompletedProcess(["docker", *args], 1, "", "Cannot connect to the Docker daemon")

    monkeypatch.setattr(runner_module, "_docker", fake_docker)
    with pytest.raises(RunnerError, match="could not list"):
        runner_module.DockerRunner().cleanup("some-task")


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


def test_cli_rejection_starts_no_container(write_plan, tmp_path, monkeypatch, capsys):
    # Before approval the harness may only read the image ID it pins into the plan.
    def inspect_only(cmd, **kwargs):
        if cmd[:3] != ["docker", "image", "inspect"]:
            raise AssertionError(f"subprocess called before approval: {cmd}")
        return subprocess.CompletedProcess(cmd, 0, "sha256:" + "a" * 64 + "\n", "")

    monkeypatch.setattr(subprocess, "run", inspect_only)
    answers = iter(["reject", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    code = cli.main(["run", str(write_plan()), "--runs-dir", str(tmp_path / "runs")])
    out = capsys.readouterr().out
    assert code == 0
    assert "No simulator was started." in out
    assert "Artifacts: " in out


def test_plan_pins_the_image_id_and_runs_only_that_image(write_plan, tmp_path):
    runner = FakeRunner()
    shown = []
    result = run_task(write_plan(), runner, lambda p: (shown.append(p.render()), ("approve", ""))[1],
                      runs_root=tmp_path / "runs")  # fmt: skip
    image_id = runner.image_info(SimBlock.image_tag)["image_id"]
    assert result.status == "completed"
    assert f"Execution image: {image_id}" in shown[0]
    assert json.loads((result.artifact_dir / "plan.json").read_text())["execution_image"] == image_id
    assert set(runner.images) == {image_id}
    assert json.loads((result.artifact_dir / "manifest.json").read_text())["image_id"] == image_id


def test_rebuilding_the_image_changes_the_plan_version(write_plan, tmp_path):
    runner = FakeRunner()
    first = run_task(write_plan(), runner, approve, runs_root=tmp_path / "runs")
    runner.rebuild(SimBlock.image_tag)
    second = run_task(write_plan(), runner, approve, runs_root=tmp_path / "runs")
    v1, v2 = (read_decisions(r.artifact_dir)[0].plan_version for r in (first, second))
    assert v1 != v2


def test_a_rebuild_after_approval_does_not_change_what_runs(write_plan, tmp_path):
    runner = FakeRunner()
    approved_id = runner.image_info(SimBlock.image_tag)["image_id"]

    def approve_then_rebuild(plan):
        runner.rebuild(SimBlock.image_tag)
        return "approve", ""

    result = run_task(write_plan(), runner, approve_then_rebuild, runs_root=tmp_path / "runs")
    assert result.status == "completed"
    assert set(runner.images) == {approved_id}


def test_a_removed_approved_image_is_refused(write_plan, tmp_path):
    runner = FakeRunner()

    def approve_then_remove(plan):
        runner.rebuild(SimBlock.image_tag, remove_old=True)
        return "approve", ""

    result = run_task(write_plan(), runner, approve_then_remove, runs_root=tmp_path / "runs")
    assert result.status == "failed"
    assert "no longer available" in result.stop_reason
    assert runner.runs == [] and runner.exports == []


def test_rerunning_a_saved_plan_reuses_its_version_and_image(write_plan, tmp_path):
    runner = FakeRunner()
    first = run_task(write_plan(), runner, approve, runs_root=tmp_path / "runs")
    approved_id = runner.image_info(SimBlock.image_tag)["image_id"]
    runner.rebuild(SimBlock.image_tag)
    again = run_task(first.artifact_dir / "plan.json", runner, approve, runs_root=tmp_path / "runs")
    assert read_decisions(again.artifact_dir)[0].plan_version == read_decisions(first.artifact_dir)[0].plan_version
    assert runner.images[-1] == approved_id
