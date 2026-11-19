"""ScriptedModel replaces the Claude API in agent tests.

It replays a fixed list of turns. A turn is either a ModelTurn or a function
that builds one from the conversation so far, which lets a script use the
plan_version that an earlier propose_plan call returned.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from abc_harness.model import ModelTurn

Step = ModelTurn | Callable[[list[dict[str, Any]]], ModelTurn]


def tool_turn(name: str, tool_input: dict[str, Any], text: str = "") -> ModelTurn:
    content: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
    content.append({"type": "tool_use", "id": f"toolu_{name}_{abs(hash(json.dumps(tool_input))) % 10**8}",
                    "name": name, "input": tool_input})  # fmt: skip
    return ModelTurn(content=content, stop_reason="tool_use", model="scripted", usage={"input_tokens": 100})


def text_turn(text: str, stop_reason: str = "end_turn") -> ModelTurn:
    return ModelTurn(content=[{"type": "text", "text": text}], stop_reason=stop_reason, model="scripted",
                     usage={"input_tokens": 100, "output_tokens": 20})  # fmt: skip


def last_tool_result(messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the most recent tool_result block the harness sent back."""
    for message in reversed(messages):
        if message["role"] == "user" and isinstance(message["content"], list):
            return message["content"][-1]
    raise AssertionError("no tool result yet")


def run_last_proposed(messages: list[dict[str, Any]]) -> ModelTurn:
    """Call run_plan with the plan_version from the latest propose_plan result."""
    version = json.loads(last_tool_result(messages)["content"])["plan_version"]
    return tool_turn("run_plan", {"plan_version": version})


class ScriptedModel:
    name = "scripted-model"

    def __init__(self, steps: list[Step]) -> None:
        self.steps = list(steps)
        self.calls: list[list[dict[str, Any]]] = []
        self.requests: list[dict[str, Any]] = []

    def create(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int = 16_384
    ) -> ModelTurn:
        self.calls.append(json.loads(json.dumps(messages)))
        self.requests.append({"system": system, "tools": [t["name"] for t in tools], "max_tokens": max_tokens})
        if not self.steps:
            raise AssertionError("ScriptedModel ran out of steps")
        step = self.steps.pop(0)
        return step(messages) if callable(step) else step
