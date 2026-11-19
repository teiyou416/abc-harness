"""Replace one exact passage in a file of the edited simulator source or the scratch directory."""

from __future__ import annotations

from typing import Any

from abc_harness.execution.workspace import EditRefused
from abc_harness.tools.base import ToolContext, ToolError
from abc_harness.tools.edits import approved_plan_with_edits

SPEC: dict[str, Any] = {
    "name": "edit_file",
    "description": "Replace one passage of a file with new text. old_text must appear exactly once in the "
    "current file. The same path rules as write_file apply: a permitted edit of the approved plan, or a file "
    "under scratch/.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_text": {"type": "string", "description": "Text copied exactly from the current file."},
            "new_text": {"type": "string", "description": "Its replacement; empty deletes it."},
        },
        "required": ["path", "old_text", "new_text"],
    },
}


def run(ctx: ToolContext, args: dict[str, Any]) -> str:
    plan = approved_plan_with_edits(ctx)
    path = str(args.get("path", ""))
    old, new = args.get("old_text"), args.get("new_text")
    if not isinstance(old, str) or not isinstance(new, str) or not old:
        raise ToolError("old_text must be non-empty text and new_text must be text")
    assert plan.execution_image is not None
    ctx.task.workspace.edited(plan.simulator, plan.execution_image)
    try:
        target = ctx.task.workspace.target(path, plan.permitted_paths)
    except EditRefused as e:
        raise ToolError(str(e)) from e
    if not target.exists():
        raise ToolError(f"{path} does not exist yet; create it with write_file")
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise ToolError(f"old_text appears {count} times in {path}; it must appear exactly once")
    target.write_text(text.replace(old, new), encoding="utf-8")
    ctx.task.trace.event("file_edited", path=path, removed_chars=len(old), added_chars=len(new))
    return f"edited {path}"
