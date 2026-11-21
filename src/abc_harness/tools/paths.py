"""The paths the agent may read, shared by read_file and search_files.

Three roots: `examples/` (example plans), `source/<simulator>/` (the original
simulator source, exported from its image on first use), and `task/` (this
task's artifact directory); in a chat session also `previous/<task_id>/`, the
artifact directory of an earlier task of the same session. A path that
resolves outside its root is refused.
"""

from __future__ import annotations

from pathlib import Path

from abc_harness.execution.runner import RunnerError
from abc_harness.simulators import SIMULATORS
from abc_harness.tools.base import ToolContext, ToolError

REPO_ROOT = Path(__file__).resolve().parents[3]
ROOTS_HINT = "path must start with examples/, source/<simulator>/, task/, or previous/<task_id>/"


def resolve(ctx: ToolContext, path: str) -> tuple[Path, Path, str]:
    """Return (root, target, prefix) for an agent path; `prefix` turns a file under root back into one."""
    head, _, rest = path.strip().rstrip("/").partition("/")
    if head == "source":
        name, _, rest = rest.partition("/")
        if name not in SIMULATORS:
            raise ToolError(f"source/ holds one folder per simulator: {', '.join(sorted(SIMULATORS))}")
        try:
            root = ctx.task.original_source(name).resolve()
        except RunnerError as e:
            raise ToolError(str(e)) from e
        prefix = f"source/{name}"
    elif head == "examples":
        root, prefix = (REPO_ROOT / "examples").resolve(), "examples"
    elif head == "task":
        root, prefix = ctx.task.artifact_dir.resolve(), "task"
    elif head == "previous":
        task_id, _, rest = rest.partition("/")
        if task_id not in ctx.previous_tasks:
            known = ", ".join(ctx.previous_tasks) or "none in this conversation"
            raise ToolError(f"previous/ holds the earlier tasks of this conversation: {known}")
        root, prefix = ctx.previous_tasks[task_id].resolve(), f"previous/{task_id}"
    else:
        raise ToolError(ROOTS_HINT)
    target = (root / (rest or ".")).resolve()
    if not target.is_relative_to(root):
        raise ToolError(f"{path} is outside {prefix}/")
    return root, target, prefix


def agent_path(root: Path, prefix: str, file: Path) -> str:
    """The path the agent would pass to read_file for `file`."""
    return f"{prefix}/{file.relative_to(root).as_posix()}"
