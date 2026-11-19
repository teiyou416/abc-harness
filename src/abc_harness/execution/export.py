"""`abc-harness export`: package a task's modified simulator source for the researcher."""

from __future__ import annotations

import tarfile
from pathlib import Path

ARCHIVE_NAME = "{task_id}-source.tar.gz"
EXTRAS = ("plan.json", "changes/edits.diff", "validation.json", "simulator_revision.txt", "report.md")


class ExportError(Exception):
    pass


def export_task(task_dir: Path) -> Path:
    """Write <task_dir>/export/<task_id>-source.tar.gz: the edited source (or the original, if the agent changed
    nothing) under src/, plus the plan, the diff, the validation result, and the report."""
    workspace = task_dir / "workspace"
    edited = workspace / "edited"
    originals = sorted((workspace / "original").glob("*")) if (workspace / "original").exists() else []
    source = edited if edited.exists() else (originals[0] if len(originals) == 1 else None)
    if source is None:
        raise ExportError(f"{task_dir} holds no simulator source to export")
    archive = task_dir / "export" / ARCHIVE_NAME.format(task_id=task_dir.name)
    archive.parent.mkdir(exist_ok=True)
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(source, arcname="src")
        for name in EXTRAS:
            if (task_dir / name).exists():
                tar.add(task_dir / name, arcname=name)
    return archive
