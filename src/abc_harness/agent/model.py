"""The model client: the only code that receives the model API key (AGENTS.md hard rule 5)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "high"
MAX_OUTPUT_TOKENS = 16_384
# List prices in USD per million tokens: input, output, cache read, 5-minute cache write (the TTL the client
# uses). Only for the cost estimate in the run statistics; update them when the published prices change.
PRICES_PER_MTOK: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-fable-5-2": (8.0, 40.0, 0.20, 10.0),
}
# On a safety decline the API reruns the request on a fallback model chosen
# by refusal category, inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_RETRIES = 3
RETRY_STATUS = {408, 409, 429}  # plus every 5xx, as the SDK's own retry rule


class ModelDeadlineExceeded(Exception):
    """The call, including its retries, did not finish before the task's remaining active time ran out."""


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

    def thinking(self) -> list[str]:
        """The model's reasoning summaries and progress notes, in order; empty blocks are left out."""
        return [b["thinking"].strip() for b in self.content if b.get("type") == "thinking" and b.get("thinking")]

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
        timeout_seconds: float | None = None,
    ) -> ModelTurn:
        """Return one model turn. With `timeout_seconds`, raise ModelDeadlineExceeded once that much time
        has passed, counting every retry."""
        ...


class AnthropicModel:
    """Calls the Claude Messages API.

    The harness retries 408, 409, 429, 5xx and connection errors itself, up to
    MAX_RETRIES times, so that every attempt and every pause between attempts
    fits inside the deadline the caller passes.
    """

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT) -> None:
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, max_retries=0)
        self.name = model
        self.effort = effort

    def create(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = MAX_OUTPUT_TOKENS,
        timeout_seconds: float | None = None,
    ) -> ModelTurn:
        started = time.monotonic()
        deadline = None if timeout_seconds is None else started + timeout_seconds
        optional: dict[str, Any] = {"tools": tools} if tools else {}
        request = dict(
            model=self.name,
            max_tokens=max_tokens,
            # An explicit breakpoint after the fixed system prompt (and the
            # tools before it), plus automatic caching of the growing
            # conversation tail.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            cache_control={"type": "ephemeral"},
            messages=messages,
            output_config={"effort": self.effort},
            # Summaries of the model's reasoning, so the researcher can follow it in the terminal and the
            # trace. Thinking is always on for this model; this only makes its text visible.
            thinking={"type": "adaptive", "display": "summarized"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
            **optional,
        )
        response = self._send(request, deadline)
        usage = {k: v for k, v in response.usage.to_dict().items() if isinstance(v, int)}
        return ModelTurn(
            content=[block.to_dict() for block in response.content],
            stop_reason=response.stop_reason or "",
            model=response.model,
            usage=usage,
            latency_seconds=round(time.monotonic() - started, 3),
            request_id=getattr(response, "_request_id", None),
        )

    def _send(self, request: dict[str, Any], deadline: float | None) -> Any:
        errors = self._anthropic
        for attempt in range(MAX_RETRIES + 1):
            left = None if deadline is None else deadline - time.monotonic()
            if left is not None and left <= 0:
                raise ModelDeadlineExceeded("the task's active time ran out before the model answered")
            try:
                client = self._client if left is None else self._client.with_options(timeout=left)
                return client.beta.messages.create(**request)
            except (errors.APIConnectionError, errors.APIStatusError) as e:
                status = getattr(e, "status_code", None)
                retryable = status is None or status in RETRY_STATUS or status >= 500
                if not retryable or attempt == MAX_RETRIES:
                    if isinstance(e, errors.APITimeoutError) and deadline is not None:
                        raise ModelDeadlineExceeded("the task's active time ran out during a model call") from e
                    raise
                pause = min(0.5 * 2**attempt, 8.0)
                if deadline is not None:
                    pause = min(pause, max(0.0, deadline - time.monotonic()))
                time.sleep(pause)
        raise AssertionError("unreachable")
