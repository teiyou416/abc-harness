"""Execute an approved plan version and summarise its results for the model."""

from __future__ import annotations

import json
import statistics
from typing import Any

from abc_harness.execution.task import STOPPED, Task
from abc_harness.planning.approval import NotApproved
from abc_harness.tools.base import EndTask, ToolContext, ToolError

SPEC: dict[str, Any] = {
    "name": "run_plan",
    "description": "Execute an approved plan version and return per-configuration results. "
    "Refused unless the researcher approved exactly this plan_version. A task runs at most one plan.",
    "input_schema": {
        "type": "object",
        "properties": {"plan_version": {"type": "string", "description": "The full plan_version string."}},
        "required": ["plan_version"],
    },
}


def run(ctx: ToolContext, args: dict[str, Any]) -> str:
    version = str(args.get("plan_version", ""))
    plan = ctx.task.plans.get(version)
    if plan is None:
        raise ToolError(f"unknown plan_version {version!r}; use the full string returned by propose_plan")
    if ctx.execution:
        raise ToolError("this task already ran a plan")
    try:
        status, reason = ctx.task.execute(plan)
    except NotApproved as e:
        raise ToolError(f"refused: {e}") from e
    ctx.execution = (status, reason)
    if status == STOPPED:
        raise EndTask(status, reason)
    return json.dumps(run_summary(ctx.task, status, reason), ensure_ascii=False)


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
    validation = None if task.validation is None else {k: v for k, v in task.validation.items() if k != "runs"}
    return {
        "plan_version": plan.version,
        "status": status,
        "status_reason": reason,
        "configurations": by_config,
        "validation": validation,
        "report": "task/report.md (written when the task ends)",
        "raw_output": "task/raw/<run_id>/",
    }
