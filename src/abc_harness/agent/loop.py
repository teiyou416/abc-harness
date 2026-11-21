"""The agent loop (docs/architecture.md, "Data flow").

The model requests a tool, the harness checks and executes the request, and the
result returns to the model. Every model call passes the budget first. The
tools themselves live in `abc_harness.tools`; this module holds the loop,
context compression, and the dispatch from tool name to tool.
"""

from __future__ import annotations

import base64
import hashlib
import time
from collections.abc import Callable, Sequence
from importlib import resources
from pathlib import Path
from typing import Any

from abc_harness.agent.context import (
    ContextLimits,
    History,
    cap_text,
    estimate_tokens,
    latest_tool_results,
    limits_note,
    new_window_message,
    render_transcript,
    task_state,
)
from abc_harness.agent.model import CONNECT_TIMEOUT_SECONDS, MAX_RETRIES, ModelClient, ModelDeadlineExceeded, ModelTurn
from abc_harness.execution.limits import Budget, LimitReached
from abc_harness.execution.runner import Runner, RunnerError
from abc_harness.execution.task import FAILED, NOT_EXECUTED, STOPPED, DecideFn, Task, TaskResult
from abc_harness.literature.figures import media_type
from abc_harness.literature.library import Library, Literature, library_pdfs, sync_index
from abc_harness.literature.pdf import PARSER_IMAGE
from abc_harness.tools import HANDLERS, TOOLS, EndTask, ToolContext, ToolError, ToolOutput
from abc_harness.tools.base import AskFn

PROMPT_FILES = ("SOUL.md", "rules.md", "compact.md")


def _prompt(name: str) -> str:
    return resources.files("abc_harness.agent").joinpath(f"prompts/{name}").read_text(encoding="utf-8")


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

    def run(self, question: str, preface: str = "") -> tuple[str, str]:
        """Run the loop. `preface` is harness text added after the question, e.g. the local library's papers."""
        self.question = question
        system = system_prompt()
        first = "\n\n".join(p for p in (question, preface, limits_note(self.task.budget)) if p)
        messages: list[dict[str, Any]] = [{"role": "user", "content": first}]
        self.history.start_window("The task starts.")
        self.history.user_text(first)
        next_input = self._estimate(system, messages)
        while True:
            if next_input > self.limits.soft_limit:
                messages = self._compress(messages, next_input)
                next_input = self._estimate(system, messages)
            if next_input > self.limits.max_input_tokens:
                raise LimitReached("context", f"about {next_input} input tokens exceed {self.limits.max_input_tokens}")
            turn = self._call_model(system, messages, TOOLS, self.limits.max_output_tokens)
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
                thinking=turn.thinking(),
                text=turn.text(),
                tool_uses=[{"name": t["name"], "input": t["input"]} for t in turn.tool_uses()],
            )
            messages.append({"role": "assistant", "content": turn.content})
            self.history.assistant(turn.content)
            # A turn that arrives after the limit, even a final answer, does not end the task normally.
            self.task.budget.check_time()
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

    def _call_model(
        self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]], max_tokens: int
    ) -> ModelTurn:
        """Make one counted model call that may use at most the task's remaining active time."""
        budget = self.task.budget
        budget.check_time()
        budget.count_llm_call()

        def report_retry(reason: str, retry: int, delay: float) -> None:
            self.task.trace.event("model_retry", call=budget.llm_calls, reason=reason, retry=retry,
                                  max_retries=MAX_RETRIES, delay_seconds=delay)

        self.task.trace.event("model_call_started", call=budget.llm_calls, window=self.history.window,
                              connect_timeout_seconds=min(CONNECT_TIMEOUT_SECONDS, budget.remaining_seconds),
                              purpose="agent" if tools else "summary")  # fmt: skip
        try:
            return self.model.create(system, messages, tools, max_tokens=max_tokens,
                                     timeout_seconds=budget.remaining_seconds, on_retry=report_retry)  # fmt: skip
        except ModelDeadlineExceeded as e:
            raise LimitReached("time", f"{e} (call {budget.llm_calls})") from e

    def _estimate(self, system: str, messages: list[dict[str, Any]]) -> int:
        return estimate_tokens(system) + estimate_tokens(TOOLS) + estimate_tokens(messages)

    def _call_tool(self, tool_use: dict[str, Any]) -> dict[str, Any]:
        name, args = tool_use["name"], tool_use.get("input") or {}
        self.task.trace.event("tool_started", name=name)
        handler = HANDLERS.get(name)
        started = time.monotonic()
        try:
            if handler is None:
                raise ToolError(f"unknown tool {name!r}")
            output, is_error = handler(self.tools, args), False
        except ToolError as e:
            output, is_error = str(e), True
        images = output.images if isinstance(output, ToolOutput) else []
        full = output.text if isinstance(output, ToolOutput) else output
        record = full + "".join(f"\n[image shown to the model: task/{rel}]" for rel, _ in images)
        self.history.tool_result(tool_use["id"], name, record, is_error)
        where = f"task/history.md (tool result id {tool_use['id']})"
        text = cap_text(full, self.limits.tool_result_max_tokens, where)
        self.task.trace.event("tool_call", tool=name, input=args, is_error=is_error, result=record[:2000],
                              result_chars=len(full), cut=text != full, images=[rel for rel, _ in images],
                              duration_seconds=round(time.monotonic() - started, 3))  # fmt: skip
        content: str | list[dict[str, Any]] = text
        if images:
            content = [{"type": "text", "text": text}] + [
                {"type": "image", "source": {"type": "base64", "media_type": media_type(data),
                                             "data": base64.b64encode(data).decode("ascii")}}
                for _, data in images
            ]  # fmt: skip
        return {"type": "tool_result", "tool_use_id": tool_use["id"], "content": content, "is_error": is_error}

    def _compress(self, messages: list[dict[str, Any]], estimated: int) -> list[dict[str, Any]]:
        """Summarize the window and start a new one (docs/development-plan.md, M2.5)."""
        budget = self.limits.hard_limit - self.limits.compact_max_tokens - estimate_tokens(_prompt("compact.md"))
        transcript = render_transcript(messages)
        if estimate_tokens(transcript) > budget:
            keep = budget * 3 - 200
            transcript = f"[the start of this window is cut; it is in task/history.md]\n\n{transcript[-keep:]}"
        turn = self._call_model(
            _prompt("compact.md"),
            [{"role": "user", "content": f"Summarize this conversation window.\n\n{transcript}"}],
            [],
            self.limits.compact_max_tokens,
        )
        if turn.stop_reason == "refusal":
            raise EndTask(FAILED, "the model declined to summarize the context window (refusal)")
        summary = turn.text() or "(the summary call returned no text; read task/history.md for earlier details)"
        old_window = self.history.window
        message = new_window_message(
            self.question, task_state(self.task, self.tools.clarifications, self.tools.library), summary, latest_tool_results(messages)
        )
        self.task.trace.event("compaction", call=self.task.budget.llm_calls, from_window=old_window,
                              estimated_input_tokens=estimated, usage=turn.usage, summary=summary)  # fmt: skip
        self.task.budget.check_time()
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
    literature: Literature | None = None,
    on_start: Callable[[Path], None] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    preface: str = "",
    previous_tasks: dict[str, Path] | None = None,
    session_id: str | None = None,
    library_dir: Path | None = None,
) -> TaskResult:
    """Run one agent task.

    PDFs under `library_dir`, the researcher's local library, are listed for the agent and parsed only when it
    reads one. In a chat session, `preface` is the harness's account of the earlier tasks, added to the first
    message, and `previous_tasks` are their artifact directories, which the agent may read.
    """
    previous_tasks = previous_tasks or {}
    limits = limits or ContextLimits()
    task = Task(runner, runs_root, budget, redact=redact, on_event=on_event, mode="agent", question=question, model=model.name,
                prompts=prompt_hashes(), context_limits=limits.__dict__,
                literature_services=literature.services if literature else [],
                session_id=session_id,
                previous_tasks=list(previous_tasks), local_library=str(library_dir) if library_dir else None)  # fmt: skip
    if on_start:
        on_start(task.artifact_dir)
    agent = Agent(task, model, ask, review, limits)
    agent.tools.previous_tasks = dict(previous_tasks)
    agent.tools.sees_images = getattr(model, "sees_images", True)
    try:
        runner.image_info(PARSER_IMAGE)
        convert = task.convert_pdf
    except RunnerError:
        convert = None  # without the parser image, PDFs cannot be read; arXiv HTML still can
    shelf = library_pdfs(library_dir) if library_dir else []
    if len(shelf) > LIBRARY_WARN_PAPERS:
        task.trace.event("library_large", library=str(library_dir), papers=len(shelf), threshold=LIBRARY_WARN_PAPERS)
    if literature is not None or shelf:
        agent.tools.library = Library(task.artifact_dir, literature, convert, library_dir=library_dir,
                                      notify=lambda kind, fields: task.trace.event(kind, **fields))  # fmt: skip
    status, stop_reason = FAILED, "unknown"
    try:
        parts = [_shelve_papers(agent.tools.library, shelf, library_dir, task) if shelf else "", preface]
        status, stop_reason = agent.run(question, "\n\n".join(p for p in parts if p))
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


LIBRARY_WARN_PAPERS = 100  # above this, the terminal suggests tidying the local library


def _shelve_papers(library: Library | None, pdfs: Sequence[Path], library_dir: Path | None, task: Task) -> str:
    """List the local library for the agent; nothing is parsed until it reads a paper."""
    assert library is not None and library_dir is not None
    lines = [(f"The researcher keeps these papers as PDFs in a local library ({library_dir}/). They are not parsed "
              "yet: open one with read_paper when you need it (the first parse takes 1 to 6 minutes, outside the "
              "time limit). A paper the researcher names in the request is the one they care about most: read it "
              "first. Before searching online, check this list; if a paper you need is here, read it instead of "
              "searching for it. Once read, it can be cited like papers found by search_papers.")]  # fmt: skip
    index = {entry["path"]: entry for entry in sync_index(library_dir).values()}
    for path in pdfs:
        relative = path.relative_to(library_dir).as_posix()
        label = f"{library_dir.name}/{relative}"
        paper = library.shelve(path, label, task.cached_pdf_output(path), index.get(relative))
        first = paper.abstract.split(". ")[0].strip()
        title = f" ({paper.title})" if paper.title != path.stem else ""
        arxiv = f" [arXiv {paper.arxiv_id}]" if paper.arxiv_id else ""
        lines.append(f"- `{paper.id}`: {label}{title}{arxiv}" + (f". {first[:200]}" if first else ""))
    return "\n".join(lines)


__all__ = ["TOOLS", "Agent", "run_agent_task"]
