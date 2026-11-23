"""The client for OpenAI's Responses API, behind the same ModelClient interface as AnthropicModel.

The agent loop, its tools, and the judge speak the Messages API format: content blocks of type text, image,
thinking, tool_use and tool_result. This module translates a request into Responses API input items and the
response back into those blocks, so nothing above it knows which provider answered.

Requests are stateless (`store: false`): OpenAI keeps no conversation. Each reasoning item comes back with
its encrypted content and is kept, verbatim, in a thinking block's `openai_item`, which the next request
sends back so the model can continue its reasoning after a tool call. The block's `thinking` text is the
reasoning summary, which the trace and history.md show like Claude's.
"""

from __future__ import annotations

import json
import time
from typing import Any

from abc_harness.agent.model import (
    DEFAULT_EFFORT,
    MAX_OUTPUT_TOKENS,
    MODELS,
    ModelTurn,
    RetryNotice,
    send_with_retries,
)


class OpenAIModel:
    """Calls OpenAI's Responses API; retries and the deadline work as in AnthropicModel."""

    def __init__(self, api_key: str, model: str = "gpt-6.2-sol", effort: str = DEFAULT_EFFORT) -> None:
        import openai

        self._openai = openai
        self._client = openai.OpenAI(api_key=api_key, max_retries=0)
        self.name = model
        self.effort = effort
        spec = MODELS.get(model)
        self.sees_images = spec.sees_images if spec else True

    def create(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = MAX_OUTPUT_TOKENS,
        timeout_seconds: float | None = None,
        on_retry: RetryNotice | None = None,
    ) -> ModelTurn:
        started = time.monotonic()
        deadline = None if timeout_seconds is None else started + timeout_seconds
        request = build_request(self.name, self.effort, system, messages, tools, max_tokens)
        response = send_with_retries(self._client.responses.create, request, self._openai, deadline, on_retry)
        data = response.to_dict()
        content, stop_reason = turn_content(data)
        return ModelTurn(
            content=content,
            stop_reason=stop_reason,
            model=data.get("model") or self.name,
            usage=usage_of(data.get("usage") or {}),
            latency_seconds=round(time.monotonic() - started, 3),
            request_id=getattr(response, "_request_id", None),
        )


def build_request(model: str, effort: str, system: str, messages: list[dict[str, Any]],
                  tools: list[dict[str, Any]], max_tokens: int) -> dict[str, Any]:
    request: dict[str, Any] = {
        "model": model,
        "instructions": system,
        "input": input_items(messages),
        "max_output_tokens": max_tokens,
        "reasoning": {"effort": effort, "summary": "auto"},
        "store": False,
        "include": ["reasoning.encrypted_content"],
    }
    if tools:
        request["tools"] = [{"type": "function", "name": t["name"], "description": t.get("description", ""),
                             "parameters": t["input_schema"], "strict": False} for t in tools]  # fmt: skip
    return request


def input_items(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Messages API messages as Responses API input items, in order."""
    items: list[dict[str, Any]] = []
    for message in messages:
        role, content = message["role"], message["content"]
        if isinstance(content, str):
            items.append({"role": role, "content": content})
        elif role == "assistant":
            items += [item for block in content if (item := _assistant_item(block))]
        else:
            parts: list[dict[str, Any]] = []
            for block in content:
                if block.get("type") == "tool_result":
                    items.append({"type": "function_call_output", "call_id": block["tool_use_id"],
                                  "output": _tool_output(block)})  # fmt: skip
                elif part := _input_part(block):
                    parts.append(part)
            if parts:
                items.append({"role": "user", "content": parts})
    return items


def _assistant_item(block: dict[str, Any]) -> dict[str, Any] | None:
    kind = block.get("type")
    if kind == "thinking":
        return block.get("openai_item")  # another provider's thinking cannot be sent back here
    if kind == "text" and block.get("text"):
        return {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": block["text"]}]}
    if kind == "tool_use":
        return {"type": "function_call", "call_id": block["id"], "name": block["name"],
                "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False)}  # fmt: skip
    return None


def _input_part(block: dict[str, Any]) -> dict[str, Any] | None:
    if block.get("type") == "text":
        return {"type": "input_text", "text": block.get("text", "")}
    if block.get("type") == "image" and (source := block.get("source") or {}).get("type") == "base64":
        return {"type": "input_image", "image_url": f"data:{source['media_type']};base64,{source['data']}"}
    return None


def _tool_output(block: dict[str, Any]) -> str | list[dict[str, Any]]:
    content = block.get("content")
    prefix = "Error: " if block.get("is_error") else ""
    if content is None or isinstance(content, str):
        return prefix + (content or "")
    parts = [part for b in content if (part := _input_part(b))]
    if not any(p["type"] == "input_image" for p in parts):
        return prefix + "\n".join(p["text"] for p in parts)
    return ([{"type": "input_text", "text": prefix.strip()}] if prefix else []) + parts


def turn_content(response: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """The response's output as Messages API content blocks, and the matching stop reason."""
    blocks: list[dict[str, Any]] = []
    refused = False
    for item in response.get("output") or []:
        kind = item.get("type")
        if kind == "reasoning":
            summary = "\n\n".join(s.get("text", "") for s in item.get("summary") or [])
            blocks.append({"type": "thinking", "thinking": summary, "openai_item": item})
        elif kind == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    blocks.append({"type": "text", "text": part.get("text", "")})
                elif part.get("type") == "refusal":
                    refused = True
                    blocks.append({"type": "text", "text": part.get("refusal", "")})
        elif kind == "function_call":
            try:
                arguments = json.loads(item.get("arguments") or "{}")
            except ValueError:
                arguments = {"_unparsed_arguments": item.get("arguments")}  # the tool reports it as invalid input
            blocks.append({"type": "tool_use", "id": item["call_id"], "name": item["name"], "input": arguments})
    incomplete = (response.get("incomplete_details") or {}).get("reason")
    if response.get("status") == "incomplete" and incomplete == "max_output_tokens":
        stop = "max_tokens"
    elif refused or incomplete == "content_filter":
        stop = "refusal"
    elif any(b["type"] == "tool_use" for b in blocks):
        stop = "tool_use"
    else:
        stop = "end_turn"
    return blocks, stop


def usage_of(usage: dict[str, Any]) -> dict[str, int]:
    """OpenAI usage in the harness's keys: its input_tokens include the cached ones, which are split out."""
    cached = int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0)
    return {
        "input_tokens": int(usage.get("input_tokens") or 0) - cached,
        "cache_read_input_tokens": cached,
        "output_tokens": int(usage.get("output_tokens") or 0),
    }
