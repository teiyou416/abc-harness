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
    assert sent[0]["max_tokens"] == 65_536


@pytest.mark.parametrize("text", ["short", "x" * 10_000])
def test_estimate_errs_high(text):
    assert estimate_tokens(text) >= len(text) / 4


def _flaky_model(failures, monkeypatch):
    import anthropic
    import httpx2

    timeouts = []

    def handle(request):
        timeouts.append(request.extensions["timeout"])
        if len(timeouts) <= failures:
            raise httpx2.ConnectTimeout("timed out", request=request)
        return httpx2.Response(200, json={
            "id": "test", "type": "message", "role": "assistant", "model": "m", "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "hi"}], "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    model = AnthropicModel("sk-test-not-used")
    model._client = anthropic.Anthropic(api_key="sk-test-not-used", max_retries=0,
                                        http_client=httpx2.Client(transport=httpx2.MockTransport(handle)))
    monkeypatch.setattr(model_module.time, "sleep", lambda s: None)
    return model, timeouts


@pytest.mark.parametrize("budget", [2, 30, None])
def test_connection_timeout_is_independent_of_response_timeout(monkeypatch, budget):
    model, timeouts = _flaky_model(2, monkeypatch)
    assert model.create("s", [{"role": "user", "content": "q"}], [], max_tokens=100, timeout_seconds=budget).text() == "hi"
    assert len(timeouts) == 3
    for timeout in timeouts:
        assert timeout["connect"] == min(5, timeout["read"])
        if budget:
            assert budget - 1 < timeout["read"] <= budget


def test_terminal_reports_retries_and_exhausted_connection_is_a_failure(tmp_path, monkeypatch):
    from abc_harness.interfaces.console import Console

    model, timeouts = _flaky_model(10, monkeypatch)
    lines = []
    result = run_agent_task("q", model, FakeRunner(), lambda q: "", lambda p: ("reject", ""),
                            runs_root=tmp_path, on_event=Console(lines.append, color=False))
    assert result.status == "failed"
    assert len(timeouts) == 4
    for retry, delay in enumerate([0.5, 1.0, 2.0], start=1):
        assert any(f"Connection timed out. Retry {retry}/3 in {delay:.1f}s." in line for line in lines)


def test_a_call_that_outlives_the_deadline_raises(monkeypatch):
    model, timeouts = _flaky_model(10, monkeypatch)
    # Keep SDK clock reads independent from the task's fake clock.
    clock = iter(range(0, 1000, 20))
    monkeypatch.setattr(model_module, "time", SimpleNamespace(monotonic=lambda: next(clock), sleep=lambda s: None))
    with pytest.raises(ModelDeadlineExceeded):
        model.create("s", [{"role": "user", "content": "q"}], [], timeout_seconds=30)
    assert len(timeouts) == 1


def _capturing(model):
    """Point the model's client at fake beta and plain endpoints; return what each received."""
    sent = {"beta": [], "plain": []}

    def endpoint(kind):
        def create(**kwargs):
            sent[kind].append(kwargs)
            block = SimpleNamespace(to_dict=lambda: {"type": "text", "text": "hi"})
            usage = SimpleNamespace(to_dict=lambda: {"input_tokens": 3, "output_tokens": 1})
            return SimpleNamespace(content=[block], stop_reason="end_turn", model=model.name, usage=usage)

        return SimpleNamespace(create=create)

    model._client = SimpleNamespace(beta=SimpleNamespace(messages=endpoint("beta")), messages=endpoint("plain"))
    return sent


def test_make_model_takes_listed_models_with_their_provider_key():
    from abc_harness.agent.model import DEEPSEEK, ModelUnavailable, make_model

    keys = {"ANTHROPIC_API_KEY": "sk-ant-x", "DEEPSEEK_API_KEY": "sk-ds-x"}
    opus = make_model("claude-opus-5-5", "high", keys.get)
    assert opus.provider.name == "Anthropic" and opus.sees_images
    pro = make_model("deepseek-v4-pro", "high", keys.get)
    assert pro.provider is DEEPSEEK and not pro.sees_images
    assert str(pro._client.base_url).startswith("https://api.deepseek.com/anthropic")
    assert make_model("deepseek-flash", "high", keys.get).sees_images
    with pytest.raises(ModelUnavailable, match="not one of the models the harness supports"):
        make_model("claude-opus-4-5", "high", keys.get)
    with pytest.raises(ModelUnavailable, match="needs DEEPSEEK_API_KEY in .env"):
        make_model("deepseek-flash", "high", {"ANTHROPIC_API_KEY": "sk-ant-x"}.get)


def test_kimi_uses_the_china_endpoint_and_only_its_effort_levels():
    from abc_harness.agent.model import KIMI, ModelUnavailable, make_model

    keys = {"MOONSHOT_API_KEY": "sk-kimi-x"}
    kimi = make_model("kimi-k3.1-pro", "high", keys.get)
    assert kimi.provider is KIMI and kimi.sees_images
    assert str(kimi._client.base_url).startswith("https://api.moonshot.cn/anthropic")
    with pytest.raises(ModelUnavailable, match="accepts effort low, high, max, not medium"):
        make_model("kimi-k3", "medium", keys.get)
    with pytest.raises(ModelUnavailable, match="needs MOONSHOT_API_KEY in .env"):
        make_model("kimi-k3", "high", {}.get)
    sent = _capturing(kimi)
    kimi.create("s", [{"role": "user", "content": "q"}], [])
    (request,) = sent["plain"]
    assert request["output_config"] == {"effort": "high"} and "betas" not in request


def test_qwen_uses_the_beijing_endpoint_enabled_thinking_and_each_models_own_options():
    from abc_harness.agent.model import QWEN, ModelUnavailable, make_model, price_for

    keys = {"DASHSCOPE_API_KEY": "sk-qwen-x"}
    big, flash = make_model("qwen4-max", "xhigh", keys.get), make_model("qwen3.8-flash", "medium", keys.get)
    assert big.provider is QWEN and big.sees_images and not flash.sees_images
    assert str(big._client.base_url).startswith("https://dashscope.aliyuncs.com/apps/anthropic")
    with pytest.raises(ModelUnavailable, match="accepts effort low, high, xhigh, not medium"):
        make_model("qwen4-max", "medium", keys.get)
    with pytest.raises(ModelUnavailable, match="accepts effort low, medium, xhigh, not high"):
        make_model("qwen3.8-flash", "high", keys.get)
    with pytest.raises(ModelUnavailable, match="needs DASHSCOPE_API_KEY in .env"):
        make_model("qwen4-max", "high", {}.get)
    sent_big, sent_flash = _capturing(big), _capturing(flash)
    big.create("s", [{"role": "user", "content": "q"}], [])
    flash.create("s", [{"role": "user", "content": "q"}], [])
    (big_request,), (flash_request,) = sent_big["plain"], sent_flash["plain"]
    assert big_request["thinking"] == {"type": "enabled"} and big_request["output_config"] == {"effort": "xhigh"}
    assert big_request["cache_control"] == {"type": "ephemeral"} and "cache_control" not in flash_request
    assert flash_request["system"][0]["cache_control"] == {"type": "ephemeral"}  # block-level caching stays
    assert price_for("qwen4-max").currency == "CNY"


def test_deepseek_requests_leave_out_the_anthropic_only_extras():
    from abc_harness.agent.model import make_model

    keys = {"ANTHROPIC_API_KEY": "a", "DEEPSEEK_API_KEY": "d"}
    claude, deepseek = make_model("claude-opus-5-5", "high", keys.get), make_model("deepseek-flash", "high", keys.get)
    sent_claude, sent_deepseek = _capturing(claude), _capturing(deepseek)
    claude.create("s", [{"role": "user", "content": "q"}], [])
    deepseek.create("s", [{"role": "user", "content": "q"}], [])
    (claude_request,), (deepseek_request,) = sent_claude["beta"], sent_deepseek["plain"]
    assert sent_claude["plain"] == [] and sent_deepseek["beta"] == []
    assert claude_request["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert claude_request["betas"] and claude_request["fallbacks"] == "default"
    assert deepseek_request["thinking"] == {"type": "adaptive"}
    assert "betas" not in deepseek_request and "fallbacks" not in deepseek_request
    assert deepseek_request["output_config"] == {"effort": "high"} and deepseek_request["model"] == "deepseek-flash"



def test_the_agent_learns_the_task_limits_from_the_harness(tmp_path):
    """The limits are set on the command line, so the prompts cannot state them; the first message does."""
    model = ScriptedModel([text_turn("No plan.")])
    run(model, tmp_path, small_limits(soft_limit=10**6), budget=Budget(time_limit_seconds=5400, llm_call_limit=40))
    first = model.calls[0][0]["content"]
    assert "- Active runtime: 90 minutes, 0 used so far" in first
    assert "- Model calls: 40, 0 used so far." in first
