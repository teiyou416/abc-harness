"""The agent loop with ScriptedModel and FakeRunner: approval gate, revisions, limits, secrets."""

from __future__ import annotations

import json

from doubles.fake_runner import FakeClock, FakeRunner
from doubles.scripted_model import ScriptedModel, last_tool_result, run_last_proposed, text_turn, tool_turn

from abc_harness.agent.loop import run_agent_task
from abc_harness.agent.secrets import Secrets
from abc_harness.execution.limits import Budget
from abc_harness.execution.trace import read_trace, summarize_trace
from abc_harness.planning.approval import read_decisions

SECRET = "sk-ant-test-secret-value-0123456789"


def plan_input(seeds=(1, 2), **baseline_extra):
    return {
        "title": "Interval comparison",
        "question": "Does a shorter interval raise the orphan rate?",
        "simulator": "simblock",
        "rationale": "SB-M4 records orphans.",
        "seeds": list(seeds),
        "metrics": ["t90_ms", "orphan_rate"],
        "run_timeout_seconds": 5,
        "baseline": {"NUM_OF_NODES": 10, "END_BLOCK_HEIGHT": 3, **baseline_extra},
        "configurations": [{"name": "slow"}, {"name": "fast", "params": {"INTERVAL": 30000}}],
    }


def decisions(*answers):
    """A review function that returns the given (decision, comment) pairs in order."""
    queue = list(answers)
    seen = []

    def review(plan):
        seen.append(plan.version)
        return queue.pop(0)

    review.seen = seen
    return review


def no_questions(question):
    raise AssertionError(f"unexpected question: {question}")


def run(model, review, tmp_path, runner=None, ask=no_questions, budget=None, redact=None):
    runner = runner or FakeRunner()
    result = run_agent_task("Compare intervals.", model, runner, ask, review, runs_root=tmp_path / "runs",
                            budget=budget, redact=redact)  # fmt: skip
    return result, runner


def test_approved_plan_runs_and_summary_reaches_the_report(tmp_path):
    model = ScriptedModel([
        tool_turn("describe_simulator", {"simulator": "simblock"}),
        tool_turn("propose_plan", plan_input()),
        run_last_proposed,
        text_turn("The fast configuration produced orphans."),
    ])  # fmt: skip
    result, runner = run(model, decisions(("approve", "")), tmp_path)
    assert result.status == "completed"
    assert runner.runs == ["slow__seed-1", "slow__seed-2", "fast__seed-1", "fast__seed-2"]
    run_result = json.loads(last_tool_result(model.calls[-1])["content"])
    assert run_result["configurations"]["fast"]["metrics"]["orphan_rate"] == {"mean": 0.25, "stdev": 0.0, "n": 2}
    report = (result.artifact_dir / "report.md").read_text()
    assert "## Agent summary" in report and "The fast configuration produced orphans." in report
    summary = summarize_trace(result.artifact_dir / "trace.jsonl")
    assert summary["model_calls"] == 4
    assert summary["tool_calls"] == {"describe_simulator": 1, "propose_plan": 1, "run_plan": 1}


def test_revision_needs_fresh_approval_and_old_version_cannot_run(tmp_path):
    v1_holder = {}

    def run_v1(messages):
        v1_holder["v"] = json.loads(last_tool_result(messages)["content"])["plan_version"]
        return tool_turn("run_plan", {"plan_version": v1_holder["v"]})

    model = ScriptedModel([
        tool_turn("propose_plan", plan_input(seeds=(1, 2))),
        run_v1,
        tool_turn("propose_plan", plan_input(seeds=(1, 2, 3))),
        run_last_proposed,
        text_turn("Done."),
    ])  # fmt: skip
    review = decisions(("revise", "use 3 seeds"), ("approve", ""))
    result, runner = run(model, review, tmp_path)
    refused = last_tool_result(model.calls[2])
    assert refused["is_error"] and "not approved" in refused["content"]
    assert result.status == "completed"
    assert len(runner.runs) == 6
    assert [d.decision for d in read_decisions(result.artifact_dir)] == ["revise", "approve"]
    assert len(list((result.artifact_dir / "plans").glob("*.json"))) == 2


def test_rejection_ends_the_task_without_another_model_call(tmp_path):
    model = ScriptedModel([tool_turn("propose_plan", plan_input()), text_turn("never reached")])
    result, runner = run(model, decisions(("reject", "not useful")), tmp_path)
    assert result.status == "rejected"
    assert len(model.calls) == 1
    assert runner.runs == [] and runner.exports == []
    assert not (result.artifact_dir / "workspace").exists()


def test_invalid_plan_is_refused_before_the_researcher_sees_it(tmp_path):
    model = ScriptedModel([
        tool_turn("propose_plan", plan_input(ALGO="pos")),
        text_turn("I could not build a valid plan."),
    ])  # fmt: skip
    review = decisions()
    result, _ = run(model, review, tmp_path)
    refused = last_tool_result(model.calls[1])
    assert refused["is_error"] and "ALGO" in refused["content"]
    assert review.seen == []
    assert result.status == "not_executed"


def test_unknown_plan_version_is_refused(tmp_path):
    model = ScriptedModel([tool_turn("run_plan", {"plan_version": "deadbeef"}), text_turn("Stopping.")])
    result, runner = run(model, decisions(), tmp_path)
    assert last_tool_result(model.calls[1])["is_error"]
    assert runner.runs == []
    assert result.status == "not_executed"


def test_llm_call_limit_stops_the_task(tmp_path):
    model = ScriptedModel([tool_turn("describe_simulator", {"simulator": "simblock"})] * 5)
    result, _ = run(model, decisions(), tmp_path, budget=Budget(llm_call_limit=2))
    assert result.status == "stopped_by_limit"
    assert len(model.calls) == 2
    assert "llm_calls" in result.stop_reason


def test_waiting_for_an_answer_does_not_count_as_active_time(tmp_path):
    clock = FakeClock()

    def slow_answer(question):
        clock.advance(5000)
        return "Use 300 nodes."

    model = ScriptedModel([tool_turn("ask_researcher", {"question": "How many nodes?"}), text_turn("Thanks.")])
    budget = Budget(time_limit_seconds=10, clock=clock)
    result, _ = run(model, decisions(), tmp_path, ask=slow_answer, budget=budget)
    manifest = json.loads((result.artifact_dir / "manifest.json").read_text())
    assert result.status == "not_executed"
    assert manifest["waiting_seconds"] == 5000
    assert last_tool_result(model.calls[1])["content"] == "Use 300 nodes."


def test_read_file_stays_inside_its_roots(tmp_path):
    (tmp_path / "outside.txt").write_text("must not be readable")
    model = ScriptedModel([
        tool_turn("read_file", {"path": "task/../../outside.txt"}),
        tool_turn("read_file", {"path": "examples/simblock-baseline.toml"}),
        text_turn("ok"),
    ])  # fmt: skip
    run(model, decisions(), tmp_path)
    first = last_tool_result(model.calls[1])
    assert first["is_error"] and "must not be readable" not in first["content"]
    second = last_tool_result(model.calls[2])
    assert not second["is_error"] and 'simulator = "simblock"' in second["content"]


def test_refusal_fails_the_task(tmp_path):
    result, _ = run(ScriptedModel([text_turn("", stop_reason="refusal")]), decisions(), tmp_path)
    assert result.status == "failed" and "refusal" in result.stop_reason


def test_secrets_never_reach_the_trace(tmp_path):
    secrets = Secrets({"ANTHROPIC_API_KEY": SECRET})
    model = ScriptedModel([text_turn(f"echoing {SECRET} by mistake")])
    result, _ = run(model, decisions(), tmp_path, redact=secrets.redact)
    trace_text = (result.artifact_dir / "trace.jsonl").read_text()
    assert SECRET not in trace_text
    assert "[REDACTED]" in trace_text
    assert read_trace(result.artifact_dir / "trace.jsonl")[-1]["event"] == "task_finished"


def test_model_call_gets_only_the_remaining_time(tmp_path):
    clock = FakeClock()
    model = ScriptedModel([text_turn("still thinking")], clock=clock, seconds_per_call=60)
    result, _ = run(model, decisions(), tmp_path, budget=Budget(time_limit_seconds=10, clock=clock))
    assert model.requests[0]["timeout_seconds"] == 10
    assert result.status == "stopped_by_limit"
    assert clock.now == 10


def test_final_answer_after_the_limit_does_not_complete_the_task(tmp_path):
    clock = FakeClock()
    model = ScriptedModel([text_turn("All done.")], clock=clock, seconds_per_call=10)
    result, _ = run(model, decisions(), tmp_path, budget=Budget(time_limit_seconds=10, clock=clock))
    assert result.status == "stopped_by_limit"
    events = [e["event"] for e in read_trace(result.artifact_dir / "trace.jsonl")]
    assert "model_call" in events and "limit_reached" in events


def test_the_agent_cannot_choose_the_execution_image(tmp_path):
    model = ScriptedModel([
        tool_turn("propose_plan", {**plan_input(), "execution_image": "sha256:" + "b" * 64}),
        lambda messages: text_turn(last_tool_result(messages)["content"]),
    ])  # fmt: skip
    review = decisions()
    result, runner = run(model, review, tmp_path)
    assert result.status == "not_executed"
    assert review.seen == [] and runner.runs == []
    assert "harness pins the image" in model.calls[1][-1]["content"][0]["content"]
