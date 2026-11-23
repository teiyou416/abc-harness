"""`abc-harness clean` and `/clean`: free disk space in `runs/` without touching evidence.

What may go, and only for a task that has ended (its `manifest.json` exists; a running task has none yet):

- `workspace/scratch/`, where the agent's sandbox builds and tests live. It is not evidence: the sandbox logs
  are in `sandbox/` and the edited source in `workspace/edited/`. Its contents are replaced by `REMOVED.md`,
  which says when and how much was removed, so the report's link to it still resolves.
- With an age limit, a whole task that ended `rejected` or `not_executed` (a chat reply included) and started
  longer ago than the limit. It ran no simulation, so no reported measurement depends on it.

Never: raw output, plans, approvals, traces, or reports of any other task, and the PDF cache.
`plan_cleanup` only lists; `apply_cleanup` removes, and callers show the list and ask first.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from abc_harness.execution.task import NOT_EXECUTED, REJECTED

REMOVED_NOTE = "REMOVED.md"
OLD_STATUSES = (REJECTED, NOT_EXECUTED)
LARGE_RUNS_BYTES = 5 * 1024**3  # above this, chat suggests /clean


@dataclass(frozen=True)
class Removal:
    path: Path
    size: int
    what: str  # "scratch" or "task"
    detail: str


def plan_cleanup(runs_root: Path, older_than_days: float | None = None, now: datetime | None = None) -> list[Removal]:
    """What a cleanup would remove under `runs_root`, removing nothing."""
    now = now or datetime.now()
    removals = []
    for task_dir in _ended_tasks(runs_root):
        status = _status(task_dir)
        started = _started(task_dir.name)
        if (older_than_days is not None and status in OLD_STATUSES and started is not None
                and now - started > timedelta(days=older_than_days)):  # fmt: skip
            removals.append(Removal(task_dir, dir_size(task_dir), "task", f"{status}, started {started:%Y-%m-%d}"))
            continue
        scratch = task_dir / "workspace" / "scratch"
        if scratch.is_dir() and any(p.name != REMOVED_NOTE for p in scratch.iterdir()):
            removals.append(Removal(scratch, dir_size(scratch), "scratch", status))
    return removals


def apply_cleanup(removals: list[Removal], now: datetime | None = None) -> int:
    """Remove what `plan_cleanup` listed. Returns the bytes freed."""
    now = now or datetime.now()
    freed = 0
    for r in removals:
        if not r.path.exists():
            continue
        if r.what == "task":
            shutil.rmtree(r.path)
        else:
            for child in r.path.iterdir():
                if child.name == REMOVED_NOTE:
                    continue
                shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
            (r.path / REMOVED_NOTE).write_text(
                f"The sandbox build and test files in this directory ({human_size(r.size)}) were removed by "
                f"`abc-harness clean` on {now:%Y-%m-%d %H:%M}. They were not results: the sandbox command output "
                "is in `sandbox/`, and the edited source in `workspace/edited/`.\n", encoding="utf-8")  # fmt: skip
        freed += r.size
    return freed


def describe(removals: list[Removal], runs_root: Path) -> list[str]:
    """One line per removal and a total, for the preview."""
    lines = []
    for r in removals:
        path = r.path.relative_to(runs_root) if r.path.is_relative_to(runs_root) else r.path
        kind = "sandbox files in" if r.what == "scratch" else "whole task"
        lines.append(f"  {human_size(r.size):>9}  {kind} {path} ({r.detail})")
    lines.append(f"  {human_size(sum(r.size for r in removals)):>9}  in total")
    return lines


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                pass
    return total


def human_size(size: float) -> str:
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _ended_tasks(runs_root: Path) -> list[Path]:
    """Ended task directories: `runs/<task_id>/` and chat replies under `runs/sessions/*/replies/`."""
    if not runs_root.is_dir():
        return []
    candidates = [p for p in runs_root.iterdir() if not p.name.startswith(".") and p.name != "sessions"]
    candidates += list(runs_root.glob("sessions/*/replies/*"))
    return sorted(p for p in candidates if p.is_dir() and (p / "manifest.json").is_file())


def _status(task_dir: Path) -> str:
    try:
        return str(json.loads((task_dir / "manifest.json").read_text(encoding="utf-8")).get("status") or "")
    except (OSError, ValueError):
        return ""


def _started(task_id: str) -> datetime | None:
    try:
        return datetime.strptime(task_id[:15], "%Y%m%d-%H%M%S")
    except ValueError:
        return None
