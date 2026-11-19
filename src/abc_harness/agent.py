"""The agent loop (docs/architecture.md, "Data flow").

The model requests a tool, the harness checks and executes the request, and the
result returns to the model. Every model call passes the budget first, and the
harness, not the model, decides what a tool may do: plans are validated in
code, approval is recorded by the harness, and `run_plan` refuses any version
without a recorded approval.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any

from abc_harness.approval import NotApproved
from abc_harness.limits import Budget, LimitReached
from abc_harness.model import ModelClient
from abc_harness.plan import PlanError, validate_plan
from abc_harness.runner import Runner
from abc_harness.simulators import SIMULATORS, SimulatorError, get_simulator
from abc_harness.task import COMPLETED, FAILED, NOT_EXECUTED, REJECTED, STOPPED, DecideFn, Task, TaskResult

AskFn = Callable[[str], str]

# Requests whose input context exceeds this stop the task (context hard limit).
CONTEXT_LIMIT_TOKENS = 800_000
REPO_ROOT = Path(__file__).resolve().parents[2]
READ_LIMIT_BYTES = 100_000

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short name of the experiment."},
        "question": {"type": "string", "description": "The research question this plan answers."},
        "simulator": {"type": "string", "enum": sorted(SIMULATORS)},
        "rationale": {
            "type": "string",
            "description": "Why this simulator fits, citing capability card entry IDs, plus assumptions and limits.",
        },
        "seeds": {"type": "array", "items": {"type": "integer"}, "description": "Distinct integer seeds."},
        "metrics": {"type": "array", "items": {"type": "string"}},
        "run_timeout_seconds": {"type": "integer", "description": "Timeout for one simulation run."},
        "baseline": {"type": "object", "description": "Parameters shared by every configuration."},
        "configurations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Letters, digits, - and _ only."},
                    "params": {"type": "object", "description": "Parameters that differ from the baseline."},
                },
                "required": ["name"],
            },
        },
    },
    "required": [
        "title", "question", "simulator", "rationale", "seeds", "metrics",
        "run_timeout_seconds", "baseline", "configurations",
    ],
}  # fmt: skip

TOOLS: list[dict[str, Any]] = [
    {
        "name": "describe_simulator",
        "description": "Return a supported simulator's capability card: what it models and does not model, "
        "run cost, metrics, and the closed set of plan parameters with allowed ranges.",
        "input_schema": {
            "type": "object",
            "properties": {"simulator": {"type": "string", "enum": sorted(SIMULATORS)}},
            "required": ["simulator"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a text file. Allowed paths: `examples/<file>` (example plans) and "
        "`task/<path>` (this task's artifact directory, for example `task/report.md` or `task/raw/<run_id>/stdout.txt`).",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
    {
        "name": "ask_researcher",
        "description": "Ask the researcher one clarification question and wait for the answer. Use only when a "
        "missing detail would change what the result means.",
        "input_schema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    },
    {
        "name": "propose_plan",
        "description": "Submit a complete experiment plan. The harness validates it, shows it to the researcher, "
        "and returns their decision (approve, revise with a comment, or reject) and the plan_version.",
        "input_schema": PLAN_SCHEMA,
    },
    {
        "name": "run_plan",
        "description": "Execute an approved plan version and return per-configuration results. "
        "Refused unless the researcher approved exactly this plan_version. A task runs at most one plan.",
        "input_schema": {
            "type": "object",
            "properties": {"plan_version": {"type": "string", "description": "The full plan_version string."}},
            "required": ["plan_version"],
        },
    },
]


class ToolError(Exception):
    """A tool request the harness refused; the message goes back to the model."""


class EndTask(Exception):
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status, self.reason = status, reason


def system_prompt() -> str:
    return resources.files("abc_harness").joinpath("prompts/system.md").read_text(encoding="utf-8")


class Agent:
    def __init__(self, task: Task, model: ModelClient, ask: AskFn, review: DecideFn) -> None:
        self.task = task
        self.model = model
        self.ask = ask
        self.review = review
        self.execution: tuple[str, str] | None = None

    # ----- the loop -----

    def run(self, question: str) -> tuple[str, str]:
        messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
        system = system_prompt()
        while True:
            self.task.budget.check_time()
            self.task.budget.count_llm_call()
            turn = self.model.create(system, messages, TOOLS)
            self.task.trace.event(
                "model_call",
                call=self.task.budget.llm_calls,
                model=turn.model,
                stop_reason=turn.stop_reason,
                usage=turn.usage,
                latency_seconds=turn.latency_seconds,
                request_id=turn.request_id,
                text=turn.text(),
                tool_uses=[{"name": t["name"], "input": t["input"]} for t in turn.tool_uses()],
            )
            messages.append({"role": "assistant", "content": turn.content})
            context = sum(turn.usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                          "cache_creation_input_tokens"))  # fmt: skip
            if context > CONTEXT_LIMIT_TOKENS:
                raise LimitReached("context", f"{context} input tokens exceed {CONTEXT_LIMIT_TOKENS}")

            if turn.stop_reason == "refusal":
                raise EndTask(FAILED, "the model declined the request (refusal)")
            if turn.stop_reason == "max_tokens":
                raise EndTask(FAILED, "the model response hit max_tokens")
            if turn.stop_reason == "pause_turn":
                continue
            tool_uses = turn.tool_uses()
            if not tool_uses:
                self.task.summary = turn.text() or None
                if self.execution:
                    return self.execution
                return NOT_EXECUTED, "the agent ended without running a plan"

            results = [self._call_tool(tool_use) for tool_use in tool_uses]
            messages.append({"role": "user", "content": results})

    def _call_tool(self, tool_use: dict[str, Any]) -> dict[str, Any]:
        name, args = tool_use["name"], tool_use.get("input") or {}
        handler = getattr(self, f"tool_{name}", None)
        try:
            if handler is None:
                raise ToolError(f"unknown tool {name!r}")
            content, is_error = handler(args), False
        except ToolError as e:
            content, is_error = str(e), True
        self.task.trace.event("tool_call", tool=name, input=args, is_error=is_error, result=content[:2000])
        return {"type": "tool_result", "tool_use_id": tool_use["id"], "content": content, "is_error": is_error}

    # ----- tools -----

    def tool_describe_simulator(self, args: dict[str, Any]) -> str:
        try:
            return get_simulator(str(args.get("simulator"))).describe()
        except SimulatorError as e:
            raise ToolError(str(e)) from e

    def tool_read_file(self, args: dict[str, Any]) -> str:
        path = str(args.get("path", ""))
        roots = {"examples": REPO_ROOT / "examples", "task": self.task.artifact_dir}
        prefix, _, rest = path.partition("/")
        if prefix not in roots or not rest:
            raise ToolError("path must start with examples/ or task/")
        root = roots[prefix].resolve()
        target = (root / rest).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ToolError(f"no readable file at {path}")
        data = target.read_bytes()
        text = data[:READ_LIMIT_BYTES].decode("utf-8", errors="replace")
        if len(data) > READ_LIMIT_BYTES:
            text += f"\n[file continues: showing the first {READ_LIMIT_BYTES} of {len(data)} bytes]"
        return text

    def tool_ask_researcher(self, args: dict[str, Any]) -> str:
        question = str(args.get("question", "")).strip()
        if not question:
            raise ToolError("question must not be empty")
        self.task.trace.event("human_wait_started", reason="clarification", question=question)
        with self.task.budget.waiting_for_human():
            answer = self.ask(question)
        self.task.trace.event("researcher_answer", answer=answer)
        return answer or "(the researcher gave no answer; choose a sensible default and say so in the plan)"

    def tool_propose_plan(self, args: dict[str, Any]) -> str:
        if self.execution:
            raise ToolError("this task already ran a plan; write your final answer instead")
        try:
            plan = validate_plan(dict(args))
        except (PlanError, SimulatorError) as e:
            raise ToolError(f"plan refused: {e}") from e
        self.task.add_plan(plan)
        decision, comment = self.task.review(plan, self.review)
        if decision == "reject":
            raise EndTask(REJECTED, "plan rejected by researcher" + (f": {comment}" if comment else ""))
        return json.dumps({"plan_version": plan.version, "decision": decision, "comment": comment})

    def tool_run_plan(self, args: dict[str, Any]) -> str:
        version = str(args.get("plan_version", ""))
        plan = self.task.plans.get(version)
        if plan is None:
            raise ToolError(f"unknown plan_version {version!r}; use the full string returned by propose_plan")
        if self.execution:
            raise ToolError("this task already ran a plan")
        try:
            status, reason = self.task.execute(plan)
        except NotApproved as e:
            raise ToolError(f"refused: {e}") from e
        self.execution = (status, reason)
        if status == STOPPED:
            raise EndTask(status, reason)
        return json.dumps(run_summary(self.task, status, reason), ensure_ascii=False)


def run_summary(task: Task, status: str, reason: str) -> dict[str, Any]:
    """What the model sees after a run: statuses and per-configuration statistics from results."""
    plan = task.executed
    assert plan is not None
    by_config: dict[str, Any] = {}
    for config in plan.data["configurations"]:
        rs = [r for r in task.records if r.configuration == config["name"]]
        done = [r for r in rs if r.status == "completed"]
        stats = {}
        for metric in plan.metrics:
            values = [r.metrics[metric] for r in done]
            stats[metric] = {
                "mean": statistics.fmean(values) if values else None,
                "stdev": statistics.stdev(values) if len(values) > 1 else None,
                "n": len(values),
            }
        by_config[config["name"]] = {
            "planned_runs": len(rs),
            "completed_runs": len(done),
            "not_completed": {r.run_id: f"{r.status}: {r.error}" for r in rs if r.status != "completed"},
            "metrics": stats,
        }
    return {
        "plan_version": plan.version,
        "status": status,
        "status_reason": reason,
        "configurations": by_config,
        "report": "task/report.md (written when the task ends)",
        "raw_output": "task/raw/<run_id>/",
    }


def run_agent_task(
    question: str,
    model: ModelClient,
    runner: Runner,
    ask: AskFn,
    review: DecideFn,
    runs_root: Path = Path("runs"),
    budget: Budget | None = None,
    redact: Callable[[str], str] | None = None,
) -> TaskResult:
    task = Task(runner, runs_root, budget, redact=redact, mode="agent", question=question, model=model.name)
    agent = Agent(task, model, ask, review)
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
        if agent.execution and status != STOPPED:
            # The simulation results stand even if the agent's last turn failed.
            run_status, run_reason = agent.execution
            if (status, stop_reason) != agent.execution:
                run_reason = f"{run_reason}; afterwards: {stop_reason}"
            status, stop_reason = run_status, run_reason
        result = task.close(status, stop_reason)
    return result


__all__ = ["COMPLETED", "TOOLS", "Agent", "run_agent_task"]
