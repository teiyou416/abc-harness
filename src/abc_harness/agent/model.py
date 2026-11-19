"""The model client: the only code that receives the model API key (AGENTS.md hard rule 5)."""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "high"
# Thinking counts toward this cap, so it leaves room for long reasoning plus a large tool input such as a plan.
MAX_OUTPUT_TOKENS = 65_536


@dataclass(frozen=True)
class Price:
    """List prices in USD per million tokens. `cache_write` is the 5-minute TTL, the one the client uses.

    A model priced by prompt length (Claude Haiku 5.5) has `above`: a request whose prompt (input, cache reads,
    and cache writes together) exceeds `above_tokens` pays those prices for all of its tokens.
    """

    input: float
    output: float
    cache_read: float
    cache_write: float
    above: Price | None = None
    above_tokens: int = 0

    def cost(self, usage: dict[str, int]) -> float:
        prompt = sum(usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        price = self.above if self.above and prompt > self.above_tokens else self
        return (usage.get("input_tokens", 0) * price.input + usage.get("output_tokens", 0) * price.output
                + usage.get("cache_read_input_tokens", 0) * price.cache_read
                + usage.get("cache_creation_input_tokens", 0) * price.cache_write) / 1_000_000  # fmt: skip


# From https://platform.claude.com/docs/en/about-claude/pricing, read 2026-11-19. Only for the cost estimate in
# the run statistics; update the table when the published prices change.
PRICES: dict[str, Price] = {
    "claude-fable-5-2": Price(8.0, 40.0, 0.20, 10.0),
    "claude-fable-5-1": Price(10.0, 50.0, 0.25, 12.50),
    "claude-fable-5": Price(10.0, 50.0, 1.0, 12.50),
    "claude-opus-5-5": Price(4.0, 20.0, 0.20, 5.0),
    "claude-opus-5": Price(5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-8": Price(5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-7": Price(5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-6": Price(5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-5": Price(5.0, 25.0, 0.50, 6.25),
    "claude-sonnet-5-5": Price(2.0, 10.0, 0.10, 2.50),
    "claude-sonnet-5": Price(2.0, 10.0, 0.20, 2.50),
    "claude-sonnet-4-6": Price(3.0, 15.0, 0.30, 3.75),
    "claude-sonnet-4-5": Price(3.0, 15.0, 0.30, 3.75),
    "claude-haiku-5-5": Price(0.10, 0.50, 0.01, 0.125, above=Price(0.50, 2.50, 0.05, 0.625), above_tokens=100_000),
    "claude-haiku-4-5": Price(1.0, 5.0, 0.10, 1.25),
}


def price_for(model: str) -> Price | None:
    """The price of a model id, matching the longest known name, so claude-opus-5-5 is not priced as claude-opus-5
    and a dated id such as claude-haiku-4-5-20251001 finds its model."""
    name = next((n for n in sorted(PRICES, key=len, reverse=True) if model.startswith(n)), None)
    return PRICES[name] if name else None
# On a safety decline the API reruns the request on a fallback model chosen
# by refusal category, inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_RETRIES = 3
RETRY_STATUS = {408, 409, 429}  # plus every 5xx, as the SDK's own retry rule


class ModelUnavailable(Exception):
    """The model cannot serve the harness's requests: unknown, or without adaptive thinking or the effort level."""


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

    def check(self, name: str) -> None:
        """Raise ModelUnavailable unless `name` exists and supports what every request uses: adaptive thinking
        and this client's effort level. Uses the Models API, which costs no tokens."""
        try:
            info = self._client.models.retrieve(name).to_dict()
        except self._anthropic.NotFoundError as e:
            raise ModelUnavailable(f"no model named {name!r}; /model lists the available ones") from e
        caps = info.get("capabilities") or {}
        thinking = ((caps.get("thinking") or {}).get("types") or {}).get("adaptive") or {}
        if not thinking.get("supported"):
            raise ModelUnavailable(f"{name} has no adaptive thinking, which the harness's requests use")
        if not ((caps.get("effort") or {}).get(self.effort) or {}).get("supported"):
            raise ModelUnavailable(f"{name} does not support effort {self.effort!r}")

    def model_ids(self) -> list[str]:
        """The models this API key can use, newest first."""
        return [m.id for m in self._client.models.list(limit=50)]

    def switched(self, name: str) -> AnthropicModel:
        """The same client (and key) calling another model."""
        other = copy.copy(self)
        other.name = name
        return other

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
