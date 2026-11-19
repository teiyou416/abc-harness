"""The agent loop (docs/architecture.md, "Data flow").

The model requests a tool, the harness checks and executes the request, and the
result returns to the model. Every model call passes the budget first. The
tools themselves live in `abc_harness.tools`; this module holds the loop,
context compression, and the dispatch from tool name to tool.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

from abc_harness.context import (
    ContextLimits,
    History,
    cap_text,
    estimate_tokens,
    latest_tool_results,
    new_window_message,
    render_transcript,
    task_state,
)
from abc_harness.limits import Budget, LimitReached
from abc_harness.model import ModelClient
from abc_harness.runner import Runner
from abc_harness.task import FAILED, NOT_EXECUTED, STOPPED, DecideFn, Task, TaskResult
from abc_harness.tools import HANDLERS, TOOLS, EndTask, ToolContext, ToolError
from abc_harness.tools.base import AskFn

PROMPT_FILES = ("SOUL.md", "rules.md", "compact.md")


def _prompt(name: str) -> str:
    return resources.files("abc_harness").joinpath(f"prompts/{name}").read_text(encoding="utf-8")


def system_prompt() -> str:
    """SOUL.md (identity and values) followed by rules.md (how this harness works)."""
    return f"{_prompt('SOUL.md').strip()}\n\n{_prompt('rules.md').strip()}\n"


def prompt_hashes() -> dict[str, str]:
    """SHA-256 of each prompt file, recorded in the manifest so a task names the prompts it ran with."""
    return {name: hashlib.sha256(_prompt(name).encode("utf-8")).hexdigest() for name in PROMPT_FILES}


class Agent:
    def __init__(
        self, task: Task, model: ModelClient, ask: AskFn, review: DecideFn, limits: ContextLimits | None = None
    ) -> None:
        self.task = task
        self.model = model
        self.tools = ToolContext(task, ask, review)
        self.limits = limits or ContextLimits()
        self.history = History(task.artifact_dir / "history.md", task.task_id)
        self.question = ""

    # ----- the loop -----

    def run(self, question: str) -> tuple[str, str]:
        self.question = question
        system = system_prompt()
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        self.history.start_window("The task starts.")
        self.history.user_text(question)
        next_input = self._estimate(system, messages)
        while True:
            if next_input > self.limits.soft_limit:
                messages = self._compress(messages, next_input)
                next_input = self._estimate(system, messages)
            if next_input > self.limits.max_input_tokens:
                raise LimitReached("context", f"about {next_input} input tokens exceed {self.limits.max_input_tokens}")
            self.task.budget.check_time()
            self.task.budget.count_llm_call()
            turn = self.model.create(system, messages, TOOLS, max_tokens=self.limits.max_output_tokens)
            actual_input = sum(turn.usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                               "cache_creation_input_tokens"))  # fmt: skip
            self.task.trace.event(
                "model_call",
                call=self.task.budget.llm_calls,
                window=self.history.window,
                model=turn.model,
                stop_reason=turn.stop_reason,
                usage=turn.usage,
                estimated_input_tokens=next_input,
                latency_seconds=turn.latency_seconds,
                request_id=turn.request_id,
                text=turn.text(),
                tool_uses=[{"name": t["name"], "input": t["input"]} for t in turn.tool_uses()],
            )
            messages.append({"role": "assistant", "content": turn.content})
            self.history.assistant(turn.content)
            if actual_input > self.limits.max_input_tokens:
                raise LimitReached("context", f"{actual_input} input tokens exceed {self.limits.max_input_tokens}")

            if turn.stop_reason == "refusal":
                raise EndTask(FAILED, "the model declined the request (refusal)")
            if turn.stop_reason == "max_tokens":
                raise EndTask(FAILED, "the model response hit max_tokens")
            if turn.stop_reason == "pause_turn":
                continue
            tool_uses = turn.tool_uses()
            if not tool_uses:
                self.task.summary = turn.text() or None
                if self.tools.execution:
                    return self.tools.execution
                return NOT_EXECUTED, "the agent ended without running a plan"

            results = [self._call_tool(tool_use) for tool_use in tool_uses]
            messages.append({"role": "user", "content": results})
            if actual_input:
                output = turn.usage.get("output_tokens") or estimate_tokens(turn.content)
                next_input = actual_input + output + estimate_tokens(results)
            else:
                next_input = self._estimate(system, messages)

    def _estimate(self, system: str, messages: list[dict[str, Any]]) -> int:
        return estimate_tokens(system) + estimate_tokens(TOOLS) + estimate_tokens(messages)

    def _call_tool(self, tool_use: dict[str, Any]) -> dict[str, Any]:
        name, args = tool_use["name"], tool_use.get("input") or {}
        handler = HANDLERS.get(name)
        try:
            if handler is None:
                raise ToolError(f"unknown tool {name!r}")
            full, is_error = handler(self.tools, args), False
        except ToolError as e:
            full, is_error = str(e), True
        self.history.tool_result(tool_use["id"], name, full, is_error)
        where = f"task/history.md (tool result id {tool_use['id']})"
        content = cap_text(full, self.limits.tool_result_max_tokens, where)
        self.task.trace.event("tool_call", tool=name, input=args, is_error=is_error, result=full[:2000],
                              result_chars=len(full), cut=content != full)  # fmt: skip
        return {"type": "tool_result", "tool_use_id": tool_use["id"], "content": content, "is_error": is_error}

    def _compress(self, messages: list[dict[str, Any]], estimated: int) -> list[dict[str, Any]]:
        """Summarize the window and start a new one (docs/development-plan.md, M2.5)."""
        self.task.budget.check_time()
        self.task.budget.count_llm_call()
        budget = self.limits.hard_limit - self.limits.compact_max_tokens - estimate_tokens(_prompt("compact.md"))
        transcript = render_transcript(messages)
        if estimate_tokens(transcript) > budget:
            keep = budget * 3 - 200
            transcript = f"[the start of this window is cut; it is in task/history.md]\n\n{transcript[-keep:]}"
        turn = self.model.create(
            _prompt("compact.md"),
            [{"role": "user", "content": f"Summarize this conversation window.\n\n{transcript}"}],
            [],
            max_tokens=self.limits.compact_max_tokens,
        )
        if turn.stop_reason == "refusal":
            raise EndTask(FAILED, "the model declined to summarize the context window (refusal)")
        summary = turn.text() or "(the summary call returned no text; read task/history.md for earlier details)"
        old_window = self.history.window
        message = new_window_message(
            self.question, task_state(self.task, self.tools.clarifications), summary, latest_tool_results(messages)
        )
        self.task.trace.event("compaction", call=self.task.budget.llm_calls, from_window=old_window,
                              estimated_input_tokens=estimated, usage=turn.usage, summary=summary)  # fmt: skip
        self.history.start_window(f"Started after window {old_window} reached the soft limit "
                                  f"(about {estimated} input tokens).")  # fmt: skip
        self.history.user_text(message, label="user (new window, written by the harness)")
        return [{"role": "user", "content": message}]


def run_agent_task(
    question: str,
    model: ModelClient,
    runner: Runner,
    ask: AskFn,
    review: DecideFn,
    runs_root: Path = Path("runs"),
    budget: Budget | None = None,
    redact: Callable[[str], str] | None = None,
    limits: ContextLimits | None = None,
) -> TaskResult:
    limits = limits or ContextLimits()
    task = Task(runner, runs_root, budget, redact=redact, mode="agent", question=question, model=model.name,
                prompts=prompt_hashes(), context_limits=limits.__dict__)  # fmt: skip
    agent = Agent(task, model, ask, review, limits)
    status, stop_reason = FAILED, "unknown"
    try:
        status, stop_reason = agent.run(question)
    except EndTask as e:
        status, stop_reason = e.status, e.reason
    except LimitReached as e:
        task.trace.event("limit_reached", limit=e.limit, detail=str(e))
        status, stop_reason = STOPPED, str(e)
    except KeyboardInterrupt:
        status, stop_reason = FAILED, "interrupted by researcher"
        raise
    except Exception as e:  # noqa: BLE001 - the report must still be written
        status, stop_reason = FAILED, f"{type(e).__name__}: {e}"
        task.trace.event("error", error=stop_reason)
    finally:
        execution = agent.tools.execution
        if execution and status != STOPPED:
            # The simulation results stand even if the agent's last turn failed.
            run_status, run_reason = execution
            if (status, stop_reason) != execution:
                run_reason = f"{run_reason}; afterwards: {stop_reason}"
            status, stop_reason = run_status, run_reason
        task.manifest["context_windows"] = agent.history.window
        result = task.close(status, stop_reason)
    return result


__all__ = ["TOOLS", "Agent", "run_agent_task"]
