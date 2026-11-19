"""Read lines of an example plan or of a file in the task's artifact directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from abc_harness.execution.runner import RunnerError
from abc_harness.simulators import SIMULATORS
from abc_harness.tools.base import ToolContext, ToolError

REPO_ROOT = Path(__file__).resolve().parents[3]
READ_DEFAULT_LINES = 400

SPEC: dict[str, Any] = {
    "name": "read_file",
    "description": "Read lines of a text file, or list a directory. Allowed paths: `examples/<file>` (example "
    "plans), `source/<simulator>/<path>` (the simulator's original source, read-only; for example "
    "`source/blocksim/` to list it), and `task/<path>` (this task's artifact directory, for example "
    "`task/history.md`, `task/raw/<run_id>/stdout.txt`, or your edited source `task/workspace/edited/<path>`). "
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
    prefix, _, rest = path.partition("/")
    if prefix == "source":
        name, _, rest = rest.partition("/")
        if name not in SIMULATORS:
            raise ToolError(f"source/ holds one folder per simulator: {', '.join(sorted(SIMULATORS))}")
        try:
            root = ctx.task.original_source(name).resolve()
        except RunnerError as e:
            raise ToolError(str(e)) from e
        rest = rest or "."
    elif prefix in ("examples", "task") and rest:
        root = (REPO_ROOT / "examples" if prefix == "examples" else ctx.task.artifact_dir).resolve()
    else:
        raise ToolError("path must start with examples/, source/<simulator>/, or task/")
    target = (root / rest).resolve()
    if not target.is_relative_to(root):
        raise ToolError(f"no readable file at {path}")
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
