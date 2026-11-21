"""Read lines of an example plan or of a file in the task's artifact directory."""

from __future__ import annotations

from typing import Any

from abc_harness.tools.base import ToolContext, ToolError
from abc_harness.tools.paths import resolve

READ_DEFAULT_LINES = 400

SPEC: dict[str, Any] = {
    "name": "read_file",
    "description": "Read lines of a text file, or list a directory. Allowed paths: `examples/<file>` (example "
    "plans), `source/<simulator>/<path>` (the simulator's original source, read-only; for example "
    "`source/blocksim/` to list it), and `task/<path>` (this task's artifact directory, for example "
    "`task/history.md`, `task/raw/<run_id>/stdout.txt`, or your edited source `task/workspace/edited/<path>`), "
    "and in a conversation `previous/<task_id>/<path>` (an earlier task's directory, e.g. its report.md). "
    "Returns at most `limit` lines starting at line `offset`.",
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
    if path.strip().rstrip("/") in ("task", "examples"):
        raise ToolError("name a file or folder inside task/ or examples/, e.g. task/history.md")
    _, target, _ = resolve(ctx, path)
    if target.is_dir():
        entries = sorted(target.iterdir())
        listing = [f"{e.name}/" if e.is_dir() else f"{e.name} ({e.stat().st_size} bytes)" for e in entries]
        return f"[{path}: directory, {len(entries)} entries]\n" + "\n".join(listing[:500])
    if not target.is_file():
        raise ToolError(f"no readable file at {path}")
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    chunk = lines[offset - 1 : offset - 1 + limit]
    last = offset - 1 + len(chunk)
    header = f"[{path}: lines {offset}-{last} of {len(lines)}]"
    if last < len(lines):
        header += f" [more: use offset {last + 1}]"
    return header + "\n" + "\n".join(chunk)
