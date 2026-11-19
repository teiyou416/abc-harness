"""The model client: the only code that receives the model API key (AGENTS.md hard rule 5)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "high"
MAX_OUTPUT_TOKENS = 16_384
# On a safety decline the API reruns the request on a fallback model chosen
# by refusal category, inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class ModelTurn:
    """One model response, reduced to plain data the loop and the trace can use."""

    content: list[dict[str, Any]]
    stop_reason: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    latency_seconds: float = 0.0
    request_id: str | None = None

    def text(self) -> str:
        return "\n".join(b["text"] for b in self.content if b.get("type") == "text").strip()

    def tool_uses(self) -> list[dict[str, Any]]:
        return [b for b in self.content if b.get("type") == "tool_use"]


class ModelClient(Protocol):
    name: str

    def create(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = MAX_OUTPUT_TOKENS,
    ) -> ModelTurn: ...


class AnthropicModel:
    """Calls the Claude Messages API. The SDK retries 429, 5xx and connection errors itself."""

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key, max_retries=3)
        self.name = model
        self.effort = effort

    def create(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = MAX_OUTPUT_TOKENS,
    ) -> ModelTurn:
        started = time.monotonic()
        optional: dict[str, Any] = {"tools": tools} if tools else {}
        response = self._client.beta.messages.create(
            model=self.name,
            max_tokens=max_tokens,
            # An explicit breakpoint after the fixed system prompt (and the
            # tools before it), plus automatic caching of the growing
            # conversation tail.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            cache_control={"type": "ephemeral"},
            messages=messages,
            output_config={"effort": self.effort},
            betas=[FALLBACK_BETA],
            fallbacks="default",
            **optional,
        )
        usage = {k: v for k, v in response.usage.to_dict().items() if isinstance(v, int)}
        return ModelTurn(
            content=[block.to_dict() for block in response.content],
            stop_reason=response.stop_reason or "",
            model=response.model,
            usage=usage,
            latency_seconds=round(time.monotonic() - started, 3),
            request_id=getattr(response, "_request_id", None),
        )
