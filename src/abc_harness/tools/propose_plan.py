"""Validate a plan, show it to the researcher, and return their decision."""

from __future__ import annotations

import json
from typing import Any

from abc_harness.execution.runner import RunnerError
from abc_harness.execution.task import FAILED, REJECTED
from abc_harness.planning.plan import PlanError, validate_plan
from abc_harness.simulators import SIMULATORS, SimulatorError
from abc_harness.tools.base import EndTask, ToolContext, ToolError

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

SPEC: dict[str, Any] = {
    "name": "propose_plan",
    "description": "Submit a complete experiment plan. The harness validates it, shows it to the researcher, "
    "and returns their decision (approve, revise with a comment, or reject) and the plan_version.",
    "input_schema": PLAN_SCHEMA,
}


def run(ctx: ToolContext, args: dict[str, Any]) -> str:
    if ctx.execution:
        raise ToolError("this task already ran a plan; write your final answer instead")
    if "execution_image" in args:
        raise ToolError("plan refused: leave out execution_image; the harness pins the image itself")
    try:
        plan = validate_plan(dict(args))
    except (PlanError, SimulatorError) as e:
        raise ToolError(f"plan refused: {e}") from e
    try:
        plan = ctx.task.pin_image(plan)
    except RunnerError as e:
        raise EndTask(FAILED, str(e)) from e
    ctx.task.add_plan(plan)
    decision, comment = ctx.task.review(plan, ctx.review)
    if decision == "reject":
        raise EndTask(REJECTED, "plan rejected by researcher" + (f": {comment}" if comment else ""))
    return json.dumps({"plan_version": plan.version, "decision": decision, "comment": comment})
