"""Offline checks against an actual task directory produced with a fake simulator."""
import json

import pytest
from doubles.fake_runner import FakeRunner

from abc_harness.execution.task import run_task
from abc_harness.interfaces.cli import main


@pytest.fixture
def task_dir(write_plan, tmp_path):
    return run_task(write_plan(), FakeRunner(), lambda _: ("approve", ""), tmp_path / "runs").artifact_dir


def check(path):
    return main(["trace", "check", str(path)])


def test_verified_and_changed_report(task_dir, capsys):
    assert check(task_dir) == 0
    assert "PASS" in capsys.readouterr().out
    report = task_dir / "report.md"
    report.write_text(report.read_text().replace("0.2500", "0.9900"))
    assert check(task_dir) == 1
    assert "report.md" in capsys.readouterr().out


def test_old_trace_and_wrong_approval(task_dir, capsys):
    path = task_dir / "trace.jsonl"
    events = [json.loads(line) for line in path.read_text().splitlines()]
    for event in events:
        if event["event"] == "run_started":
            event.pop("plan_version")
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    assert check(task_dir) == 2
    assert "INSUFFICIENT" in capsys.readouterr().out
    for event in events:
        if event["event"] == "plan_decision":
            event["decision"] = "reject"
    path.write_text("".join(json.dumps(e) + "\n" for e in events))
    assert check(task_dir) == 1


def test_missing_raw_output(task_dir):
    (task_dir / "raw/base__seed-1/blockList.txt").unlink()
    assert check(task_dir) == 2


def test_validation_precedes_formal_runs_and_checks_blocksim(tmp_path):
    from test_edits import coding_steps, run

    result, _, _ = run(coding_steps(), tmp_path)
    directory = result.artifact_dir
    assert check(directory) == 0
    path = directory / "trace.jsonl"
    data = [json.loads(line) for line in path.read_text().splitlines()]
    validation = next(e for e in data if e["event"] == "validation_finished")
    validation["passed"] = False
    path.write_text("".join(json.dumps(e) + "\n" for e in data))
    assert check(directory) == 1


def test_rejected_without_execution_and_missing_directory(write_plan, tmp_path):
    result = run_task(write_plan(), FakeRunner(), lambda _: ("reject", ""), tmp_path / "runs")
    assert check(result.artifact_dir) == 0
    assert check(tmp_path / "absent") == 2
