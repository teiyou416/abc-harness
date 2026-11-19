"""Write a whole file in the edited simulator source or the scratch directory."""

from __future__ import annotations

from typing import Any

from abc_harness.execution.workspace import EditRefused
from abc_harness.tools.base import ToolContext, ToolError
from abc_harness.tools.edits import approved_plan_with_edits

MAX_FILE_CHARS = 200_000

SPEC: dict[str, Any] = {
    "name": "write_file",
    "description": "Create or overwrite a file. Paths are relative to the simulator source root and must be a "
    "permitted edit of the approved plan; files under scratch/ (your tests and notes) are always allowed. Only "
    "after the researcher approved a plan with permitted edits. Read the original source with read_file "
    "(source/<simulator>/...) and your edited copy at task/workspace/edited/...",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "e.g. Models/Bitcoin/Node.py or scratch/test_strategy.py"},
            "content": {"type": "string", "description": "The complete new content of the file."},
        },
        "required": ["path", "content"],
    },
}


def run(ctx: ToolContext, args: dict[str, Any]) -> str:
    plan = approved_plan_with_edits(ctx)
    path, content = str(args.get("path", "")), args.get("content")
    if not isinstance(content, str):
        raise ToolError("content must be text")
    if len(content) > MAX_FILE_CHARS:
        raise ToolError(f"content is longer than {MAX_FILE_CHARS} characters")
    assert plan.execution_image is not None
    ctx.task.workspace.edited(plan.simulator, plan.execution_image)
    try:
        target = ctx.task.workspace.target(path, plan.permitted_paths)
    except EditRefused as e:
        raise ToolError(str(e)) from e
    existed = target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    ctx.task.trace.event("file_written", path=path, chars=len(content), created=not existed)
    return f"{'replaced' if existed else 'created'} {path} ({len(content.splitlines())} lines)"
