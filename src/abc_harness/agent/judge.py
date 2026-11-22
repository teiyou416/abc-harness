"""The on-demand judge: a model's advice on whether a finished task's final answer is supported by its results.

It runs only when the researcher asks, after the task ended, for a task that executed a plan and whose
`trace check` found no FAIL. It reads the task's saved artifacts, calls one model through the same client as
the agent (at most JUDGE_CALLS calls: one retry for an unreadable verdict), and appends one record to
`judge.jsonl`. It changes nothing else: the judgment is advice labelled as model-assessed, never evidence.
See docs/project-spec.md#judge.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from pathlib import Path
from typing import Any

from abc_harness.agent.model import ModelClient, ModelDeadlineExceeded, price_for
from abc_harness.execution.grounding import split_summary
from abc_harness.execution.trace_check import check_task

JUDGE_CALLS = 2
# Thinking counts toward it; 4,096 let deepseek-v4-pro think past its verdict on a 45-configuration task. Billing
# follows what is used, so a high cap costs nothing when the judge needs little.
JUDGE_MAX_TOKENS = 16384
JUDGE_TIMEOUT_SECONDS = 120.0
JUDGE_EFFORT = "low"
DIMENSION = "conclusion_supported"
RECORD_FILE = "judge.jsonl"
# The cheaper capable models first; the first one with a key that is not the task's own model judges by default.
JUDGE_PREFERENCE = ("claude-sonnet-5-5", "kimi-k3.1-pro", "deepseek-v4-pro", "deepseek-flash", "claude-opus-5-5",
                    "kimi-k3", "claude-haiku-5-5", "claude-fable-5-2", "kimi-k3.1-pro-highspeed")  # fmt: skip
TYPICAL_OUTPUT_TOKENS = 1000  # for the estimate; JUDGE_MAX_TOKENS bounds it
# Length caps on each part of the judge's input, in characters.
CAPS = {"question": 2000, "plan": 6000, "tables": 10000, "validation": 2000, "check": 3000, "answer": 8000}
REPORT_SECTIONS = ("## Planned versus completed runs", "## Results", "## Code changes and validation")
RETRY_NOTE = "Your reply could not be read. Reply with ONLY the JSON object the instructions describe."


class JudgeRefused(Exception):
    """The task cannot be judged: it executed no plan, has no final answer, or its evidence check failed."""


@dataclass(frozen=True)
class JudgeInput:
    task_dir: Path
    task_model: str
    message: str  # the user message the judge gets

    def estimate(self, model: str) -> tuple[float, float, str] | None:
        """(typical cost, at most, currency) for one call, or None without a list price."""
        price = price_for(model)
        if price is None:
            return None
        tokens_in = (len(rubric()) + len(self.message.encode("utf-8"))) / 4
        typical = price.cost({"input_tokens": int(tokens_in), "output_tokens": TYPICAL_OUTPUT_TOKENS})
        most = price.cost({"input_tokens": int(tokens_in), "output_tokens": JUDGE_MAX_TOKENS}) * JUDGE_CALLS
        return typical, most, getattr(price, "currency", "USD")


def rubric() -> str:
    return resources.files("abc_harness.agent").joinpath("prompts/judge.md").read_text(encoding="utf-8")


def rubric_hash() -> str:
    return hashlib.sha256(rubric().encode("utf-8")).hexdigest()


def prepare(task_dir: Path, redact: Callable[[str], str] = lambda s: s) -> JudgeInput:
    """Check that the task can be judged and build the judge's input from its artifacts."""
    manifest = _read_json(task_dir / "manifest.json")
    if manifest is None:
        raise JudgeRefused(f"{task_dir} has no manifest.json: it is not a finished task")
    if not (task_dir / "plan.json").exists():
        raise JudgeRefused("this task executed no plan, so there are no results to judge its answer against")
    report = _read_text(task_dir / "report.md")
    answer, _ = split_summary(report)
    if not answer.strip():
        raise JudgeRefused("this task has no final answer from the agent to judge")
    check = _read_json(task_dir / "trace_check.json")
    lines = check["lines"] if check else check_task(task_dir)[1]
    failures = [line for line in lines if line.startswith("FAIL")]
    if failures:
        raise JudgeRefused("the evidence check found contradictions, so judging the answer would not mean "
                           f"anything; fix those first: {failures[0]}")  # fmt: skip
    plan = _read_json(task_dir / "plan.json") or {}
    plan_text = json.dumps({k: v for k, v in plan.items() if k not in ("citations",)}, ensure_ascii=False, indent=1)
    tables = "\n\n".join(_section(report, heading) for heading in REPORT_SECTIONS if heading in report)
    validation = _read_text(task_dir / "validation.json")
    parts = [
        ("The researcher's question", manifest.get("question") or "(none recorded; see the plan)", "question"),
        ("The executed plan (plan.json)", plan_text, "plan"),
        ("Tables computed by the harness from the raw output", tables, "tables"),
        ("Validation check (validation.json)", validation or "(the plan had none)", "validation"),
        ("The harness's evidence check", "\n".join(lines), "check"),
        ("The agent's final answer", answer.strip(), "answer"),
    ]
    message = "\n\n".join(f"## {title}\n\n{_cap(text, CAPS[key])}" for title, text, key in parts)
    return JudgeInput(task_dir, str(manifest.get("model") or ""), redact(message))


def default_model(task_model: str, has_key: Callable[[str], bool]) -> str | None:
    """The first preferred model with a key in .env that is not the task's own model."""
    from abc_harness.agent.model import MODELS

    for name in JUDGE_PREFERENCE:
        if name in MODELS and name != task_model and has_key(MODELS[name].provider.key_name):
            return name
    return None


def judge(prepared: JudgeInput, model: ModelClient, now: Callable[[], datetime] = datetime.now) -> dict[str, Any]:
    """Call the judge, append its record to judge.jsonl, and return the record."""
    import anthropic  # imported where used, as in agent/model.py

    messages: list[dict[str, Any]] = [{"role": "user", "content": prepared.message}]
    usage: dict[str, int] = {}
    cost: dict[str, float] = {}
    verdict, error, calls, answered_by, cut = None, None, 0, model.name, False
    for _ in range(JUDGE_CALLS):
        calls += 1
        try:
            turn = model.create(rubric(), messages, [], max_tokens=JUDGE_MAX_TOKENS,
                                timeout_seconds=JUDGE_TIMEOUT_SECONDS)  # fmt: skip
        except ModelDeadlineExceeded:
            error = f"the judge did not answer within {JUDGE_TIMEOUT_SECONDS:.0f} seconds"
            break
        except anthropic.APIError as e:  # after the client's own retries; recorded, since a call was made
            error = f"the judge's model API failed: {type(e).__name__} {getattr(e, 'status_code', '') or ''}".strip()
            break
        answered_by = turn.model or model.name
        for k, v in turn.usage.items():
            usage[k] = usage.get(k, 0) + v
        price = price_for(answered_by)
        if price is not None:
            currency = getattr(price, "currency", "USD")
            cost[currency] = cost.get(currency, 0.0) + price.cost(turn.usage, now())
        verdict = parse_verdict(turn.text())
        if verdict is not None:
            break
        cut = turn.stop_reason == "max_tokens"
        messages += [{"role": "assistant", "content": turn.content}, {"role": "user", "content": RETRY_NOTE}]
    record = {
        "ts": now().astimezone().isoformat(timespec="seconds"),
        "status": "scored" if verdict else ("error" if error else "no_verdict"),
        "dimension": DIMENSION,
        **(verdict or {"score": None, "reason": error or _no_verdict_reason(cut), "faulted": []}),
        "judge_model": answered_by,
        "effort": getattr(model, "effort", None),
        "task_model": prepared.task_model,
        "same_model_as_task": answered_by == prepared.task_model,
        "rubric_sha256": rubric_hash(),
        "model_calls": calls,
        "usage": usage,
        "estimated_cost": {k: round(v, 6) for k, v in cost.items()},
        "label": "model-assessed advice, not evidence",
    }
    with (prepared.task_dir / RECORD_FILE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def _no_verdict_reason(cut: bool) -> str:
    if cut:
        return f"the judge's reply was cut at the {JUDGE_MAX_TOKENS:,}-token output limit before its verdict"
    return "the judge's reply held no readable verdict"


def parse_verdict(text: str) -> dict[str, Any] | None:
    """The score, reason, and faulted sentences from the judge's JSON reply, or None if it cannot be read."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
        score = obj[DIMENSION]
        if isinstance(score, bool) or not isinstance(score, int | float):
            return None
        faulted = obj.get("faulted") or []
        return {"score": max(0, min(10, round(score))), "reason": str(obj.get("reason") or "")[:600],
                "faulted": [str(s)[:400] for s in faulted if isinstance(s, str)][:10]}  # fmt: skip
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def latest(task_dir: Path) -> dict[str, Any] | None:
    path = task_dir / RECORD_FILE
    if not path.exists():
        return None
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    try:
        return json.loads(lines[-1]) if lines else None
    except ValueError:
        return None


def _section(report: str, heading: str) -> str:
    start = report.find(heading)
    end = report.find("\n## ", start + len(heading))
    return report[start: len(report) if end < 0 else end].strip()


def _cap(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n[cut: {len(text) - limit} more characters]"


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except ValueError:
        return None
