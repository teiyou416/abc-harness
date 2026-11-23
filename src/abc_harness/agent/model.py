"""The model client: the only code that receives a model API key (AGENTS.md hard rule 5).

Three providers serve the same Messages API: Anthropic, and DeepSeek and
Moonshot (Kimi) through their Anthropic-compatible endpoints. `MODELS` is the whole list of models the
harness may use, with each one's provider, list price, and whether it can see
images; `make_model` builds the client for one of them with that provider's key.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

DEFAULT_MODEL = "deepseek-flash"  # what --model chooses when not given
DEFAULT_EFFORT = "high"
EFFORTS = ("low", "medium", "high", "xhigh", "max")  # the values output_config.effort accepts
# Thinking counts toward this cap, so it leaves room for long reasoning plus a large tool input such as a plan.
MAX_OUTPUT_TOKENS = 65_536
# On a safety decline the Anthropic API reruns the request on a fallback model chosen
# by refusal category, inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
CONNECT_TIMEOUT_SECONDS = 5.0
MAX_RETRIES = 3
RETRY_STATUS = {408, 409, 429}  # plus every 5xx, as the SDK's own retry rule


RetryNotice = Callable[[str, int, float], None]


@dataclass(frozen=True)
class Price:
    """List prices per million tokens, in `currency`. `cache_write` is the 5-minute TTL, the one the client uses.

    A model priced by prompt length (Claude Haiku 5.5) has `above`: a request whose prompt (input, cache reads,
    and cache writes together) exceeds `above_tokens` pays those prices for all of its tokens. A model priced by
    time of day (DeepSeek) has `off_peak`, used for a request made outside the provider's peak hours.
    """

    input: float
    output: float
    cache_read: float
    cache_write: float
    above: Price | None = None
    above_tokens: int = 0
    off_peak: Price | None = None
    currency: str = "USD"

    def cost(self, usage: dict[str, int], when: datetime | None = None) -> float:
        price = self.off_peak if self.off_peak and when is not None and not deepseek_peak(when) else self
        prompt = sum(usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        price = price.above if price.above and prompt > price.above_tokens else price
        return (usage.get("input_tokens", 0) * price.input + usage.get("output_tokens", 0) * price.output
                + usage.get("cache_read_input_tokens", 0) * price.cache_read
                + usage.get("cache_creation_input_tokens", 0) * price.cache_write) / 1_000_000  # fmt: skip


def deepseek_peak(when: datetime) -> bool:
    """DeepSeek's peak hours: 01:00-04:00 and 06:00-10:00 UTC, Monday to Friday. Chinese public holidays are
    off-peak too, which this check does not know, so an estimate on such a day is high."""
    when = when.astimezone(UTC)
    return when.weekday() < 5 and (1 <= when.hour < 4 or 6 <= when.hour < 10)


@dataclass(frozen=True)
class Provider:
    name: str
    key_name: str  # the .env entry holding its API key
    base_url: str | None
    anthropic_extras: bool  # the beta endpoint with server-side fallback and summarized thinking
    efforts: tuple[str, ...] = EFFORTS  # the effort values it accepts
    api: str = "messages"  # "messages" (Anthropic's Messages API or a compatible one) or "responses" (OpenAI's)
    thinking: str = "adaptive"  # the thinking type it accepts; Qwen knows only "enabled" and "disabled"


ANTHROPIC = Provider("Anthropic", "ANTHROPIC_API_KEY", None, True)
DEEPSEEK = Provider("DeepSeek", "DEEPSEEK_API_KEY", "https://api.deepseek.com/anthropic", False)
# The China platform (platform.moonshot.cn); its keys do not work on the international one (api.moonshot.ai).
KIMI = Provider("Moonshot", "MOONSHOT_API_KEY", "https://api.moonshot.cn/anthropic", False,
                efforts=("low", "high", "max"))
# OpenAI's own Responses API, through agent/openai_model.py. The GPT-6 models reject effort "none"; "max" is
# left out until a model page confirms it.
OPENAI = Provider("OpenAI", "OPENAI_API_KEY", None, False, efforts=("low", "medium", "high", "xhigh"),
                  api="responses")
# Alibaba Model Studio (Bailian), Beijing region. The legacy host needs no workspace id in the URL; keys from the
# Singapore region do not work here. Effort levels differ by model (ModelSpec.efforts).
QWEN = Provider("Alibaba", "DASHSCOPE_API_KEY", "https://dashscope.aliyuncs.com/apps/anthropic", False,
                thinking="enabled")
API_KEY_NAMES = (ANTHROPIC.key_name, DEEPSEEK.key_name, KIMI.key_name, OPENAI.key_name, QWEN.key_name)


@dataclass(frozen=True)
class ModelSpec:
    provider: Provider
    price: Price
    sees_images: bool = True
    efforts: tuple[str, ...] | None = None  # when the model accepts fewer effort levels than its provider
    conversation_cache: bool = True  # the request-level cache_control that caches the growing conversation


def efforts_of(spec: ModelSpec) -> tuple[str, ...]:
    return spec.efforts or spec.provider.efforts


def _deepseek(hit: float, miss: float, output: float) -> Price:
    """Peak prices, with off-peak at half. A cache miss is billed as plain input; there is no write charge."""
    off = Price(miss / 2, output / 2, hit / 2, miss / 2)
    return Price(miss, output, hit, miss, off_peak=off)


def _openai(input: float, cached: float, output: float) -> Price:
    """USD; a request whose prompt exceeds 272K tokens pays twice the input and 1.5 times the output price.
    OpenAI caches by itself and charges no cache writes."""
    long = Price(input * 2, output * 1.5, cached * 2, input * 2)
    return Price(input, output, cached, input, above=long, above_tokens=272_000)


def _kimi(miss: float, hit: float, write_5m: float, output: float) -> Price:
    """China-platform prices in CNY."""
    return Price(miss, output, hit, write_5m, currency="CNY")


# The models the harness may use. Claude prices from https://platform.claude.com/docs/en/about-claude/pricing and
# DeepSeek prices from https://api-docs.deepseek.com/quick_start/pricing, both read 2026-11-19; Kimi prices from
# the China price table at https://platform.kimi.com/docs/pricing/chat, as the maintainer read it on 2026-11-22;
# OpenAI prices from https://developers.openai.com/api/docs/pricing and Qwen (Beijing) prices from
# https://help.aliyun.com/zh/model-studio/model-pricing, both read 2026-11-23.
# Update them when the published prices change; they feed only the cost estimate in the run statistics.
MODELS: dict[str, ModelSpec] = {
    "claude-opus-5-5": ModelSpec(ANTHROPIC, Price(4.0, 20.0, 0.20, 5.0)),
    "claude-sonnet-5-5": ModelSpec(ANTHROPIC, Price(2.0, 10.0, 0.10, 2.50)),
    "claude-haiku-5-5": ModelSpec(ANTHROPIC, Price(0.10, 0.50, 0.01, 0.125, above=Price(0.50, 2.50, 0.05, 0.625),
                                                   above_tokens=100_000)),
    "claude-fable-5-2": ModelSpec(ANTHROPIC, Price(8.0, 40.0, 0.20, 10.0)),
    # deepseek-v4-pro replaces images with "[Unsupported Image]", so it cannot read figures.
    "deepseek-v4-pro": ModelSpec(DEEPSEEK, _deepseek(0.044, 1.32, 3.96), sees_images=False),
    "deepseek-flash": ModelSpec(DEEPSEEK, _deepseek(0.006, 0.30, 1.20)),
    "kimi-k3.1-pro": ModelSpec(KIMI, _kimi(13.0, 1.30, 13.0, 68.0)),
    "kimi-k3.1-pro-highspeed": ModelSpec(KIMI, _kimi(26.0, 1.30, 26.0, 136.0)),
    "kimi-k3": ModelSpec(KIMI, _kimi(20.0, 2.0, 20.0, 100.0)),
    "gpt-6.2-sol": ModelSpec(OPENAI, _openai(2.0, 0.10, 10.0)),
    "gpt-6.2-astra": ModelSpec(OPENAI, _openai(8.0, 0.40, 40.0)),
    "gpt-6-luna": ModelSpec(OPENAI, _openai(0.10, 0.01, 0.50)),
    "qwen4-max": ModelSpec(QWEN, Price(10.0, 30.0, 0.50, 12.5, currency="CNY"), efforts=("low", "high", "xhigh")),
    # The page gives no cache prices for qwen3.8-flash; these follow its example rule (hit 10%, write 125% of
    # input). Its image input is unverified, so the tools treat it as blind; it rejects request-level caching.
    "qwen3.8-flash": ModelSpec(QWEN, Price(0.80, 2.70, 0.08, 1.0, currency="CNY"), sees_images=False,
                               efforts=("low", "medium", "xhigh"), conversation_cache=False),
}


def price_for(model: str) -> Price | None:
    """The price of a model id, matching the longest known name, so a dated id finds its model."""
    name = next((n for n in sorted(MODELS, key=len, reverse=True) if model.startswith(n)), None)
    return MODELS[name].price if name else None


class ModelUnavailable(Exception):
    """The model is not on the list, or its provider's API key is missing."""


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
        on_retry: RetryNotice | None = None,
    ) -> ModelTurn:
        """Return one model turn. With `timeout_seconds`, raise ModelDeadlineExceeded once that much time
        has passed, counting every retry."""
        ...


def make_model(name: str, effort: str, key: Callable[[str], str | None]) -> ModelClient:
    """The client for a listed model, with its provider's key from `key(name_of_env_entry)`."""
    spec = MODELS.get(name)
    if spec is None:
        raise ModelUnavailable(f"{name!r} is not one of the models the harness supports: {', '.join(MODELS)}")
    api_key = key(spec.provider.key_name)
    if not api_key:
        raise ModelUnavailable(f"{name} needs {spec.provider.key_name} in .env")
    if effort not in efforts_of(spec):
        raise ModelUnavailable(f"{name} accepts effort {', '.join(efforts_of(spec))}, not {effort}")
    if spec.provider.api == "responses":
        from abc_harness.agent.openai_model import OpenAIModel

        return OpenAIModel(api_key, model=name, effort=effort)
    return AnthropicModel(api_key, model=name, effort=effort, provider=spec.provider)


class AnthropicModel:
    """Calls a Messages API: Anthropic's, or DeepSeek's Anthropic-compatible one.

    The harness retries 408, 409, 429, 5xx and connection errors itself, up to
    MAX_RETRIES times, so that every attempt and every pause between attempts
    fits inside the deadline the caller passes.
    """

    def __init__(
        self, api_key: str, model: str = "claude-opus-5-5", effort: str = DEFAULT_EFFORT, provider: Provider = ANTHROPIC
    ) -> None:
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, base_url=provider.base_url, max_retries=0)
        self.name = model
        self.effort = effort
        self.provider = provider
        spec = MODELS.get(model)
        self.sees_images = spec.sees_images if spec else True
        self.conversation_cache = spec.conversation_cache if spec else True

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
        request: dict[str, Any] = {
            "model": self.name,
            "max_tokens": max_tokens,
            # An explicit breakpoint after the fixed system prompt (and the
            # tools before it), plus automatic caching of the growing
            # conversation tail. DeepSeek ignores both and caches by itself.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "cache_control": {"type": "ephemeral"},
            "messages": messages,
            "output_config": {"effort": self.effort},
            "thinking": {"type": self.provider.thinking},
        }
        if not self.conversation_cache:
            del request["cache_control"]
        if tools:
            request["tools"] = tools
        if self.provider.anthropic_extras:
            # Request reasoning summaries for the saved trace.
            request.update(thinking={"type": "adaptive", "display": "summarized"}, betas=[FALLBACK_BETA],
                           fallbacks="default")  # fmt: skip
        response = self._send(request, deadline, on_retry)
        usage = {k: v for k, v in response.usage.to_dict().items() if isinstance(v, int)}
        return ModelTurn(
            content=[block.to_dict() for block in response.content],
            stop_reason=response.stop_reason or "",
            model=response.model,
            usage=usage,
            latency_seconds=round(time.monotonic() - started, 3),
            request_id=getattr(response, "_request_id", None),
        )

    def _send(self, request: dict[str, Any], deadline: float | None, on_retry: RetryNotice | None) -> Any:
        messages = self._client.beta.messages if self.provider.anthropic_extras else self._client.messages
        return send_with_retries(messages.create, request, self._anthropic, deadline, on_retry)


def send_with_retries(create: Callable[..., Any], request: dict[str, Any], errors: Any, deadline: float | None,
                      on_retry: RetryNotice | None) -> Any:
    """Call `create(**request)`, retrying 408, 409, 429, 5xx and connection errors up to MAX_RETRIES times, so
    that every attempt and every pause fits before `deadline`. `errors` is the SDK module (anthropic or openai),
    whose error classes and Timeout have the same names in both."""
    from httpx2 import ConnectTimeout

    for attempt in range(MAX_RETRIES + 1):
        left = None if deadline is None else deadline - time.monotonic()
        if left is not None and left <= 0:
            raise ModelDeadlineExceeded("the task's active time ran out before the model answered")
        try:
            if left is not None:
                request["timeout"] = errors.Timeout(left, connect=min(CONNECT_TIMEOUT_SECONDS, left))
            return create(**request)
        except (errors.APIConnectionError, errors.APIStatusError) as e:
            status = getattr(e, "status_code", None)
            retryable = status is None or status in RETRY_STATUS or status >= 500
            remaining = None if deadline is None else deadline - time.monotonic()
            if retryable and remaining is not None and remaining <= 0:
                raise ModelDeadlineExceeded("the task's active time ran out during a model call") from e
            if not retryable or attempt == MAX_RETRIES:
                raise
            pause = 0.5 * 2**attempt
            if remaining is not None and remaining <= pause:
                time.sleep(remaining)
                raise ModelDeadlineExceeded("the task's active time ran out before the next retry") from e
            if on_retry:
                if status is not None:
                    reason = f"Model API returned HTTP {status}."
                elif isinstance(e.__cause__, ConnectTimeout):
                    reason = "Connection timed out."
                elif isinstance(e, errors.APITimeoutError):
                    reason = "Model request timed out."
                else:
                    reason = "Connection failed."
                on_retry(reason, attempt + 1, pause)
            time.sleep(pause)
    raise AssertionError("unreachable")
