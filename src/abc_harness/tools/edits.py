"""What write_file, edit_file, and run_command share: they work only for an approved plan with permitted edits."""

from __future__ import annotations

from abc_harness.planning.plan import Plan
from abc_harness.tools.base import ToolContext, ToolError


def approved_plan_with_edits(ctx: ToolContext) -> Plan:
    if ctx.execution:
        raise ToolError("the plan has already run; the edited source is frozen")
    plan = ctx.task.approved_plan()
    if plan is None:
        raise ToolError("no approved plan: propose a plan with permitted_edits and wait for approval first")
    if not plan.permitted_paths:
        raise ToolError("the approved plan permits no edits; propose a new plan version with permitted_edits")
    return plan
