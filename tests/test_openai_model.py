"""The OpenAI client: Messages API blocks in, Responses API items out, and back, against a mock HTTP server."""

from __future__ import annotations

import json

import httpx2
import openai
import pytest

from abc_harness.agent import model as model_module
from abc_harness.agent.model import OPENAI, ModelUnavailable, make_model, price_for
from abc_harness.agent.openai_model import OpenAIModel, input_items, turn_content, usage_of

TOOLS = [{"name": "describe_simulator", "description": "Describe one simulator.",
          "input_schema": {"type": "object", "properties": {"simulator": {"type": "string"}}}}]  # fmt: skip
REASONING = {"type": "reasoning", "id": "rs_1", "encrypted_content": "gAAA-opaque",
             "summary": [{"type": "summary_text", "text": "I should look at BlockSim first."}]}  # fmt: skip


def response(output, status="completed", usage=None, incomplete=None):
    return {"id": "resp_1", "object": "response", "created_at": 0, "model": "gpt-6.2-sol-2026-11-01",
            "status": status, "output": output, "incomplete_details": incomplete, "parallel_tool_calls": True,
            "tool_choice": "auto", "tools": [],
            "usage": usage or {"input_tokens": 1200, "input_tokens_details": {"cached_tokens": 1000},
                               "output_tokens": 80, "output_tokens_details": {"reasoning_tokens": 50},
                               "total_tokens": 1280}}  # fmt: skip


def mock_model(replies, monkeypatch=None):
    sent = []

    def handle(request):
        sent.append(json.loads(request.content))
        reply = replies.pop(0)
        return reply if isinstance(reply, httpx2.Response) else httpx2.Response(200, json=reply)

    model = OpenAIModel("sk-test-not-used", effort="medium")
    model._client = openai.OpenAI(api_key="sk-test-not-used", max_retries=0,
                                  http_client=httpx2.Client(transport=httpx2.MockTransport(handle)))  # fmt: skip
    if monkeypatch:
        monkeypatch.setattr(model_module.time, "sleep", lambda s: None)
    return model, sent


def test_a_tool_call_turn_and_its_reasoning_go_back_with_the_tool_result():
    call = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "describe_simulator",
            "arguments": '{"simulator": "blocksim"}', "status": "completed"}  # fmt: skip
    answer = {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
              "content": [{"type": "output_text", "text": "BlockSim fits.", "annotations": []}]}  # fmt: skip
    model, sent = mock_model([response([REASONING, call]), response([answer])])

    messages = [{"role": "user", "content": "Which simulator?"}]
    turn = model.create("system text", messages, TOOLS, max_tokens=500)
    assert turn.stop_reason == "tool_use" and turn.model == "gpt-6.2-sol-2026-11-01"
    assert turn.thinking() == ["I should look at BlockSim first."]
    assert turn.tool_uses() == [{"type": "tool_use", "id": "call_1", "name": "describe_simulator",
                                 "input": {"simulator": "blocksim"}}]  # fmt: skip
    assert turn.usage == {"input_tokens": 200, "cache_read_input_tokens": 1000, "output_tokens": 80}

    first = sent[0]
    assert first["instructions"] == "system text" and first["store"] is False
    assert first["reasoning"] == {"effort": "medium", "summary": "auto"} and first["max_output_tokens"] == 500
    assert first["tools"] == [{"type": "function", "name": "describe_simulator", "description": "Describe one simulator.",
                               "parameters": TOOLS[0]["input_schema"], "strict": False}]  # fmt: skip
    assert first["input"] == [{"role": "user", "content": "Which simulator?"}]

    messages += [{"role": "assistant", "content": turn.content},
                 {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "card"}]}]
    final = model.create("system text", messages, TOOLS)
    assert final.stop_reason == "end_turn" and final.text() == "BlockSim fits."
    assert sent[1]["input"][1:] == [
        REASONING,  # verbatim, encrypted content included, so the model continues its reasoning
        {"type": "function_call", "call_id": "call_1", "name": "describe_simulator",
         "arguments": '{"simulator": "blocksim"}'},
        {"type": "function_call_output", "call_id": "call_1", "output": "card"},
    ]  # fmt: skip


def test_images_errors_and_other_providers_thinking_are_translated():
    image = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBOR"}}
    items = input_items([
        {"role": "assistant", "content": [{"type": "thinking", "thinking": "Claude's", "signature": "s"},
                                          {"type": "text", "text": "Looking."}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "c1", "content": [{"type": "text", "text": "figure 2"}, image]},
            {"type": "tool_result", "tool_use_id": "c2", "content": "no such file", "is_error": True},
            {"type": "text", "text": "Also this."}]},
    ])  # fmt: skip
    assert items == [
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Looking."}]},
        {"type": "function_call_output", "call_id": "c1", "output": [
            {"type": "input_text", "text": "figure 2"},
            {"type": "input_image", "image_url": "data:image/png;base64,iVBOR"}]},
        {"type": "function_call_output", "call_id": "c2", "output": "Error: no such file"},
        {"role": "user", "content": [{"type": "input_text", "text": "Also this."}]},
    ]  # fmt: skip


@pytest.mark.parametrize(("status", "incomplete", "output", "stop"), [
    ("incomplete", {"reason": "max_output_tokens"}, [REASONING], "max_tokens"),
    ("completed", None, [{"type": "message", "role": "assistant",
                          "content": [{"type": "refusal", "refusal": "I can't help."}]}], "refusal"),
    ("completed", None, [{"type": "function_call", "call_id": "c", "name": "x", "arguments": "{bad"}], "tool_use"),
])  # fmt: skip
def test_stop_reasons_map_to_the_loops_own(status, incomplete, output, stop):
    blocks, reason = turn_content({"status": status, "incomplete_details": incomplete, "output": output})
    assert reason == stop
    if stop == "tool_use":
        assert blocks[0]["input"] == {"_unparsed_arguments": "{bad"}


def test_rate_limits_are_retried_like_the_other_providers(monkeypatch):
    answer = {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "hi"}]}
    model, sent = mock_model([httpx2.Response(429, json={"error": {"message": "slow down"}}), response([answer])],
                             monkeypatch)  # fmt: skip
    notices = []
    assert model.create("s", [{"role": "user", "content": "q"}], [], on_retry=lambda *a: notices.append(a)).text() == "hi"
    assert len(sent) == 2 and notices[0][0] == "Model API returned HTTP 429."


def test_openai_models_are_listed_with_their_key_efforts_and_prices():
    model = make_model("gpt-6.2-sol", "high", {"OPENAI_API_KEY": "sk-x"}.get)
    assert isinstance(model, OpenAIModel) and model.effort == "high"
    with pytest.raises(ModelUnavailable, match="needs OPENAI_API_KEY in .env"):
        make_model("gpt-6-luna", "high", {}.get)
    with pytest.raises(ModelUnavailable, match="accepts effort low, medium, high, xhigh, not max"):
        make_model("gpt-6-luna", "max", {"OPENAI_API_KEY": "sk-x"}.get)
    assert OPENAI.key_name == "OPENAI_API_KEY"

    price = price_for("gpt-6.2-sol-2026-11-01")
    short = usage_of({"input_tokens": 1_200_000 // 10, "output_tokens": 0})
    assert price.cost(short) == pytest.approx(0.24)  # 120K uncached input at $2
    long = {"input_tokens": 300_000, "output_tokens": 10_000}
    assert price.cost(long) == pytest.approx(0.3 * 4 + 0.01 * 15)  # above 272K: $4 input, $15 output
