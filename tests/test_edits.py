"""M5: permitted edits, sandbox exec, the validation check, and export, with FakeRunner and ScriptedModel."""

from __future__ import annotations

import json
import tarfile

import pytest
from doubles.fake_runner import FakeClock, FakeRunner
from doubles.scripted_model import ScriptedModel, last_tool_result, run_last_proposed, text_turn, tool_turn

from abc_harness.agent.loop import run_agent_task
from abc_harness.execution.export import export_task
from abc_harness.execution.limits import Budget
from abc_harness.execution.runner import RunOutcome
from abc_harness.execution.trace import read_trace
from abc_harness.planning.plan import PlanError, validate_plan

STRATEGY = "Models/Bitcoin/Strategy.py"
BASE = {"simTime": 86400, "HASH_POWERS": [50, 20, 30]}


def edit_plan(**overrides):
    plan = {
        "title": "Selfish mining", "question": "q", "simulator": "blocksim",
        "rationale": "BlockSim lacks selfish mining (BS-N2); SimBlock too (SB-N1).", "seeds": [1, 2],
        "metrics": ["stale_rate", "node0_block_share"], "run_timeout_seconds": 30, "baseline": BASE,
        "configurations": [{"name": "selfish"}, {"name": "honest", "edits": False}],
        "permitted_edits": [{"path": STRATEGY, "purpose": "node 0 withholds blocks"}],
        "validation": {"description": "Eyal and Sirer closed form", "params": {"HASH_POWERS": [1, 2]}, "seeds": [7],
                       "metric": "node0_block_share", "expected": 0.625, "tolerance": 0.01},
    }  # fmt: skip
    plan.update(overrides)
    return plan


def run(steps, tmp_path, runner=None, budget=None, review=None):
    runner = runner or FakeRunner()
    model = ScriptedModel(steps)
    result = run_agent_task("Does selfish mining pay?", model, runner, lambda q: "", review or (lambda p: ("approve", "")),
                            runs_root=tmp_path / "runs", budget=budget)  # fmt: skip
    return result, runner, model


def said(model, call):
    """The text of the last tool result the model saw in its `call`-th request."""
    content = model.calls[call][-1]["content"][0]["content"]
    return content if isinstance(content, str) else content[0]["text"]


@pytest.mark.parametrize(("change", "message"), [
    ({"validation": None}, "needs a validation check"),
    ({"permitted_edits": [], "configurations": [{"name": "a"}]}, "validation check belongs"),
    ({"permitted_edits": [{"path": "../evil.py", "purpose": "x"}]}, "plain path"),
    ({"permitted_edits": [{"path": "/etc/passwd", "purpose": "x"}]}, "plain path"),
    ({"permitted_edits": [{"path": STRATEGY}]}, "path and a purpose"),
    ({"metrics": ["stale_rate"]}, "validation metric must be one of"),
])  # fmt: skip
def test_edit_plans_are_validated(change, message):
    data = edit_plan(**change)
    data = {k: v for k, v in data.items() if v is not None}
    with pytest.raises(PlanError, match=message):
        validate_plan(data)


def test_edits_flag_needs_permitted_edits():
    data = edit_plan(configurations=[{"name": "a", "edits": False}])
    del data["permitted_edits"], data["validation"]
    with pytest.raises(PlanError, match="only when the plan has permitted edits"):
        validate_plan(data)


def test_review_shows_edits_validation_and_which_source_each_configuration_runs():
    text = validate_plan(edit_plan()).render()
    assert f"{STRATEGY}: node 0 withholds blocks" in text
    assert "passes if the mean node0_block_share is 0.625 ± 0.01" in text
    assert "honest: baseline [original source]" in text and "selfish: baseline [edited source]" in text


def coding_steps(plan=None):
    return [
        tool_turn("read_file", {"path": "source/blocksim/"}),
        tool_turn("propose_plan", plan or edit_plan()),
        tool_turn("write_file", {"path": STRATEGY, "content": "SELFISH = True\n"}),
        tool_turn("write_file", {"path": "scratch/test_strategy.py", "content": "assert True\n"}),
        tool_turn("run_command", {"command": "python /work/scratch/test_strategy.py"}),
        run_last_proposed_after_tools,
        text_turn("Done."),
    ]


def run_last_proposed_after_tools(messages):
    """run_plan with the version from the propose_plan result, several turns back."""
    for message in reversed(messages):
        if message["role"] == "user" and isinstance(message["content"], list):
            content = message["content"][0].get("content")
            if isinstance(content, str) and content.startswith('{"plan_version"'):
                return tool_turn("run_plan", {"plan_version": json.loads(content)["plan_version"]})
    raise AssertionError("no plan proposed")


def test_agent_writes_tests_validates_and_runs_both_sources(tmp_path):
    seen = {}
    runner = FakeRunner(inspect=lambda run_id, workdir: seen.setdefault(run_id, (workdir / "src" / STRATEGY).exists()))
    result, runner, model = run(coding_steps(), tmp_path, runner)
    assert result.status == "completed", result.stop_reason
    assert "InputsConfig.py (" in said(model, 1)  # the source listing before approval
    assert seen == {"validation__seed-7": True, "selfish__seed-1": True, "selfish__seed-2": True,
                    "honest__seed-1": False, "honest__seed-2": False}  # fmt: skip
    assert runner.runs[0] == "validation__seed-7"
    assert runner.sandbox_calls == ["python /work/scratch/test_strategy.py"]
    d = result.artifact_dir
    assert "+SELFISH = True" in (d / "changes" / "edits.diff").read_text()
    assert (d / "workspace" / "scratch" / "test_strategy.py").exists()
    assert "$ python /work/scratch/test_strategy.py" in (d / "sandbox" / "001.log").read_text()
    assert json.loads((d / "validation.json").read_text())["passed"] is True
    report = (d / "report.md").read_text()
    assert "## Code changes and validation" in report and "**passed**" in report and "not a result" in report
    events = [e["event"] for e in read_trace(d / "trace.jsonl")]
    assert events.index("sandbox_finished") < events.index("edits_frozen") < events.index("validation_finished")
    archive = export_task(d)
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert f"src/{STRATEGY}" in names and "changes/edits.diff" in names and "validation.json" in names


def test_failed_validation_stops_the_task_before_any_configuration(tmp_path):
    plan = edit_plan(validation={**edit_plan()["validation"], "expected": 0.33, "tolerance": 0.02})
    result, runner, _ = run(coding_steps(plan), tmp_path)
    assert result.status == "failed"
    assert "validation check failed: mean node0_block_share 0.625 is outside 0.33 ± 0.02" in result.stop_reason
    assert runner.runs == ["validation__seed-7"]
    assert all(r.status == "missing" for r in result.runs)
    assert "**failed; no configuration was run**" in (result.artifact_dir / "report.md").read_text()


@pytest.mark.parametrize(("tool", "args", "message"), [
    ("write_file", {"path": "Models/Bitcoin/Node.py", "content": "x"}, "not a permitted edit"),
    ("write_file", {"path": "../outside.py", "content": "x"}, "plain relative path"),
    ("edit_file", {"path": STRATEGY, "old_text": "x", "new_text": "y"}, "does not exist yet"),
])  # fmt: skip
def test_writes_outside_the_permitted_files_are_refused(tmp_path, tool, args, message):
    steps = [tool_turn("propose_plan", edit_plan()), tool_turn(tool, args),
             lambda m: text_turn(last_tool_result(m)["content"])]  # fmt: skip
    result, _, model = run(steps, tmp_path)
    assert message in said(model, 2)
    assert not (result.artifact_dir / "outside.py").exists()
    assert not (result.artifact_dir / "workspace" / "edited" / "Models" / "Bitcoin" / "Node.py").exists()


@pytest.mark.parametrize("tool", ["write_file", "run_command"])
def test_nothing_is_written_or_run_before_approval(tmp_path, tool):
    args = {"path": STRATEGY, "content": "x"} if tool == "write_file" else {"command": "ls"}
    steps = [tool_turn("propose_plan", edit_plan()), tool_turn(tool, args),
             lambda m: text_turn(last_tool_result(m)["content"])]  # fmt: skip
    result, runner, model = run(steps, tmp_path, review=lambda p: ("revise", "more seeds"))
    assert "no approved plan" in said(model, 2)
    assert runner.sandbox_calls == [] and not (result.artifact_dir / "workspace" / "edited").exists()


def test_edit_file_replaces_exactly_one_passage(tmp_path):
    steps = [
        tool_turn("propose_plan", edit_plan()),
        tool_turn("write_file", {"path": STRATEGY, "content": "a = 1\na = 1\nb = 2\n"}),
        tool_turn("edit_file", {"path": STRATEGY, "old_text": "a = 1", "new_text": "a = 3"}),
        tool_turn("edit_file", {"path": STRATEGY, "old_text": "b = 2", "new_text": "b = 4"}),
        text_turn("ok"),
    ]  # fmt: skip
    result, _, model = run(steps, tmp_path)
    assert "appears 2 times" in said(model, 3)
    assert (result.artifact_dir / "workspace" / "edited" / STRATEGY).read_text() == "a = 1\na = 1\nb = 4\n"


def test_a_change_outside_the_permitted_files_blocks_the_run(tmp_path):
    def tamper(messages):
        edited = next((tmp_path / "runs").iterdir()) / "workspace" / "edited"
        (edited / "InputsConfig.py").write_text("# changed behind the harness's back\n")
        return run_last_proposed_after_tools(messages)

    steps = [tool_turn("propose_plan", edit_plan()), tool_turn("write_file", {"path": STRATEGY, "content": "x\n"}),
             tamper, lambda m: text_turn(last_tool_result(m)["content"])]  # fmt: skip
    _, runner, model = run(steps, tmp_path)
    assert "does not permit: InputsConfig.py" in said(model, 3)
    assert runner.runs == []


def test_sandbox_time_counts_toward_the_task_limit(tmp_path):
    clock = FakeClock()
    runner = FakeRunner(clock=clock, seconds_per_run=8,
                        sandbox_handler=lambda c, s, w: RunOutcome(None, True, 2, "partial output"))  # fmt: skip
    steps = [tool_turn("propose_plan", edit_plan()), tool_turn("run_command", {"command": "sleep 100"})]
    result, runner, _ = run(steps, tmp_path, runner, budget=Budget(time_limit_seconds=5, clock=clock))
    assert result.status == "stopped_by_limit"
    assert "sandbox command 1" in result.stop_reason
    assert "partial output" in (result.artifact_dir / "sandbox" / "001.log").read_text()


def test_read_file_lists_and_reads_the_original_source(tmp_path):
    steps = [tool_turn("read_file", {"path": "source/blocksim/"}),
             tool_turn("read_file", {"path": "source/blocksim/Main.py", "limit": 3}),
             tool_turn("read_file", {"path": "source/ethereum/x"}), text_turn("ok")]  # fmt: skip
    _, _, model = run(steps, tmp_path)
    assert "[source/blocksim/: directory" in said(model, 1)
    assert said(model, 2).startswith("[source/blocksim/Main.py: lines 1-3")
    assert "one folder per simulator" in said(model, 3)


def test_a_plan_without_edits_runs_as_before(tmp_path):
    data = edit_plan(configurations=[{"name": "base"}])
    del data["permitted_edits"], data["validation"]
    steps = [tool_turn("propose_plan", data), run_last_proposed, text_turn("ok")]
    result, runner, _ = run(steps, tmp_path)
    assert result.status == "completed" and runner.runs == ["base__seed-1", "base__seed-2"]
    assert not (result.artifact_dir / "validation.json").exists()
