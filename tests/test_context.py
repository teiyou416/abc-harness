"""Context management (M2.5): soft-limit compression, task state, tool-result caps, hard limit, prompts."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from doubles.fake_runner import FakeRunner
from doubles.scripted_model import ScriptedModel, text_turn, tool_turn

from abc_harness.agent import loop as agent_module
from abc_harness.agent import model as model_module
from abc_harness.agent.context import ContextLimits, estimate_tokens, task_state
from abc_harness.agent.loop import TOOLS, prompt_hashes, run_agent_task, system_prompt
from abc_harness.agent.model import AnthropicModel, ModelDeadlineExceeded
from abc_harness.execution.limits import Budget
from abc_harness.execution.task import Task
from abc_harness.execution.trace import read_trace
from abc_harness.planning.plan import validate_plan
from abc_harness.tools import ToolContext, read_file

QUESTION = "Compare intervals."


def no_usage(turn):
    """Drop usage so the agent falls back to its own estimate, as with a provider that reports none."""
    turn.usage = {}
    return turn


def initial_estimate() -> int:
    return estimate_tokens(system_prompt()) + estimate_tokens(TOOLS) + estimate_tokens([{"role": "user",
                                                                                        "content": QUESTION}])  # fmt: skip


def run(model, tmp_path, limits, budget=None):
    return run_agent_task(QUESTION, model, FakeRunner(), lambda q: "", lambda p: ("approve", ""),
                          runs_root=tmp_path / "runs", budget=budget, limits=limits)  # fmt: skip


def small_limits(**overrides):
    values = {"soft_limit": initial_estimate() + 500, "hard_limit": 200_000, "max_output_tokens": 1000,
              "compact_max_tokens": 500, "tool_result_max_tokens": 8192}  # fmt: skip
    values.update(overrides)
    return ContextLimits(**values)


def test_soft_limit_compresses_into_a_new_window(tmp_path):
    model = ScriptedModel([
        no_usage(tool_turn("describe_simulator", {"simulator": "simblock"})),
        text_turn("The agent read the SimBlock card. The 30 s configuration had orphan_rate 0.99."),
        text_turn("Done."),
    ])  # fmt: skip
    result = run(model, tmp_path, small_limits())
    assert result.status == "not_executed"

    compaction_request = model.requests[1]
    assert compaction_request["tools"] == [] and compaction_request["max_tokens"] == 500
    assert "Summarize this conversation window" in model.calls[1][0]["content"]

    new_window = model.calls[2]
    assert len(new_window) == 1 and new_window[0]["role"] == "user"
    text = new_window[0]["content"]
    for part in ("## Original question", QUESTION, "## Task state", "No plan has been executed yet.",
                 "orphan_rate 0.99", "## Latest tool results", "SimBlock capability card", "task/history.md"):  # fmt: skip
        assert part in text

    history = (result.artifact_dir / "history.md").read_text()
    assert "## Window 1" in history and "## Window 2" in history
    assert "Revision: SimBlock" in history
    events = [e["event"] for e in read_trace(result.artifact_dir / "trace.jsonl")]
    assert events.count("compaction") == 1
    manifest = json.loads((result.artifact_dir / "manifest.json").read_text())
    assert manifest["context_windows"] == 2
    assert manifest["llm_calls"] == 3


def test_task_state_comes_from_harness_records(tmp_path):
    task = Task(FakeRunner(), tmp_path / "runs", Budget())
    plan = task.pin_image(validate_plan({
        "title": "Intervals", "question": "q", "simulator": "simblock", "rationale": "r", "seeds": [1, 2],
        "metrics": ["orphan_rate"], "run_timeout_seconds": 5,
        "baseline": {"NUM_OF_NODES": 10, "END_BLOCK_HEIGHT": 3}, "configurations": [{"name": "base"}],
    }))  # fmt: skip
    task.add_plan(plan)
    task.review(plan, lambda p: ("approve", ""))
    task.execute(plan)
    state = task_state(task, [("How many nodes?", "Ten.")])
    assert f"approve `{plan.version}`" in state
    assert '"mean": 0.25' in state
    assert "Q: How many nodes?\n  A: Ten." in state
    task.close("completed", "test")


def test_long_tool_results_are_cut_but_kept_in_history(tmp_path):
    model = ScriptedModel([tool_turn("describe_simulator", {"simulator": "simblock"}), text_turn("ok")])
    result = run(model, tmp_path, small_limits(soft_limit=10**6, tool_result_max_tokens=200))
    sent = model.calls[1][-1]["content"][0]["content"]
    assert len(sent) <= 200 * 3
    assert "the full text is in task/history.md (tool result id" in sent
    assert "Revision: SimBlock" in (result.artifact_dir / "history.md").read_text()


def test_hard_limit_stops_when_compression_cannot_make_room(tmp_path):
    model = ScriptedModel([text_turn("summary")])
    limits = ContextLimits(soft_limit=100, hard_limit=2000, max_output_tokens=1000, compact_max_tokens=500)
    result = run(model, tmp_path, limits)
    assert result.status == "stopped_by_limit"
    assert "context" in result.stop_reason
    assert len(model.calls) == 1  # only the summary call ran


def test_summary_calls_count_toward_the_call_limit(tmp_path):
    model = ScriptedModel([no_usage(tool_turn("describe_simulator", {"simulator": "simblock"})), text_turn("x")])
    result = run(model, tmp_path, small_limits(), budget=Budget(llm_call_limit=1))
    assert result.status == "stopped_by_limit"
    assert "llm_calls" in result.stop_reason
    assert len(model.calls) == 1


def test_read_file_pages_through_lines(tmp_path):
    task = Task(FakeRunner(), tmp_path / "runs", Budget())
    (task.artifact_dir / "notes.txt").write_text("\n".join(f"line {i}" for i in range(1, 11)))
    ctx = ToolContext(task, lambda q: "", lambda p: ("reject", ""))
    page = read_file.run(ctx, {"path": "task/notes.txt", "offset": 3, "limit": 2})
    assert page.splitlines() == ["[task/notes.txt: lines 3-4 of 10] [more: use offset 5]", "line 3", "line 4"]
    task.close("not_executed", "test")


def test_prompt_hashes_follow_prompt_content(tmp_path, monkeypatch):
    model = ScriptedModel([text_turn("ok")])
    result = run(model, tmp_path, small_limits(soft_limit=10**6))
    manifest = json.loads((result.artifact_dir / "manifest.json").read_text())
    assert set(manifest["prompts"]) == {"SOUL.md", "rules.md", "compact.md"}
    assert model.requests[0]["system"].startswith("# Who you are")

    original = agent_module._prompt
    monkeypatch.setattr(agent_module, "_prompt", lambda name: original(name) + ("x" if name == "SOUL.md" else ""))
    changed = prompt_hashes()
    assert changed["SOUL.md"] != manifest["prompts"]["SOUL.md"]
    assert changed["rules.md"] == manifest["prompts"]["rules.md"]


def test_anthropic_request_enables_caching_and_omits_empty_tools():
    model = AnthropicModel("sk-test-not-used")
    sent = []

    def fake_create(**kwargs):
        sent.append(kwargs)
        block = SimpleNamespace(to_dict=lambda: {"type": "text", "text": "hi"})
        usage = SimpleNamespace(to_dict=lambda: {"input_tokens": 10, "output_tokens": 2})
        return SimpleNamespace(content=[block], stop_reason="end_turn", model="m", usage=usage)

    model._client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=fake_create)))
    model.create("system text", [{"role": "user", "content": "q"}], [])
    model.create("system text", [{"role": "user", "content": "q"}], TOOLS, max_tokens=500)
    assert sent[0]["system"] == [{"type": "text", "text": "system text", "cache_control": {"type": "ephemeral"}}]
    assert sent[0]["cache_control"] == {"type": "ephemeral"}
    assert "tools" not in sent[0]
    assert sent[1]["tools"] is TOOLS and sent[1]["max_tokens"] == 500
    assert sent[0]["max_tokens"] == 16_384


@pytest.mark.parametrize("text", ["short", "x" * 10_000])
def test_estimate_errs_high(text):
    assert estimate_tokens(text) >= len(text) / 4


class _FlakyMessages:
    def __init__(self, failures, error):
        self.failures, self.error, self.timeouts = failures, error, []

    def create(self, **kwargs):
        if self.failures:
            self.failures -= 1
            raise self.error
        block = SimpleNamespace(to_dict=lambda: {"type": "text", "text": "hi"})
        usage = SimpleNamespace(to_dict=lambda: {"input_tokens": 1})
        return SimpleNamespace(content=[block], stop_reason="end_turn", model="m", usage=usage)


def _flaky_model(failures, monkeypatch):
    import anthropic

    # Only the type matters to the retry rule; skip the constructor's HTTP request object.
    error = anthropic.APIConnectionError.__new__(anthropic.APIConnectionError)
    messages = _FlakyMessages(failures, error)
    model = AnthropicModel("sk-test-not-used")

    def with_options(timeout):
        messages.timeouts.append(timeout)
        return SimpleNamespace(beta=SimpleNamespace(messages=messages))

    model._client = SimpleNamespace(with_options=with_options)
    monkeypatch.setattr(model_module.time, "sleep", lambda s: None)
    return model, messages


def test_retries_happen_inside_the_deadline(monkeypatch):
    model, messages = _flaky_model(2, monkeypatch)
    assert model.create("s", [{"role": "user", "content": "q"}], [], timeout_seconds=30).text() == "hi"
    assert len(messages.timeouts) == 3
    assert all(0 < t <= 30 for t in messages.timeouts)


def test_a_call_that_outlives_the_deadline_raises(monkeypatch):
    model, messages = _flaky_model(10, monkeypatch)
    clock = iter(range(0, 1000, 20))
    monkeypatch.setattr(model_module.time, "monotonic", lambda: next(clock))
    with pytest.raises(ModelDeadlineExceeded):
        model.create("s", [{"role": "user", "content": "q"}], [], timeout_seconds=30)
    assert len(messages.timeouts) == 1
