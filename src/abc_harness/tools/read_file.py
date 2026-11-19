"""Read lines of an example plan or of a file in the task's artifact directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abc_harness.tools.base import ToolContext, ToolError

REPO_ROOT = Path(__file__).resolve().parents[3]
READ_DEFAULT_LINES = 400

SPEC: dict[str, Any] = {
    "name": "read_file",
    "description": "Read lines of a text file. Allowed paths: `examples/<file>` (example plans) and "
    "`task/<path>` (this task's artifact directory, for example `task/history.md`, `task/report.md`, or "
    "`task/raw/<run_id>/stdout.txt`). Returns at most `limit` lines starting at line `offset`.",
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "offset": {"type": "integer", "description": "First line to return, starting at 1. Default 1."},
            "limit": {"type": "integer", "description": f"Number of lines. Default {READ_DEFAULT_LINES}."},
        },
        "required": ["path"],
    },
}


def run(ctx: ToolContext, args: dict[str, Any]) -> str:
    path = str(args.get("path", ""))
    try:
        offset = max(1, int(args.get("offset") or 1))
        limit = max(1, int(args.get("limit") or READ_DEFAULT_LINES))
    except (TypeError, ValueError) as e:
        raise ToolError("offset and limit must be whole numbers") from e
    roots = {"examples": REPO_ROOT / "examples", "task": ctx.task.artifact_dir}
    prefix, _, rest = path.partition("/")
    if prefix not in roots or not rest:
        raise ToolError("path must start with examples/ or task/")
    root = roots[prefix].resolve()
    target = (root / rest).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise ToolError(f"no readable file at {path}")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    chunk = lines[offset - 1 : offset - 1 + limit]
    last = offset - 1 + len(chunk)
    header = f"[{path}: lines {offset}-{last} of {len(lines)}]"
    if last < len(lines):
        header += f" [more: use offset {last + 1}]"
    return header + "\n" + "\n".join(chunk)
