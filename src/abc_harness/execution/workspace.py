"""The task workspace: the original simulator source, the agent's edited copy, and a scratch directory.

    workspace/original/<simulator>/   exported from the execution image; never changed
    workspace/edited/                 the agent's copy; changed only by write_file and edit_file
    workspace/scratch/                the only directory sandbox exec can write to
    workspace/runs/<run_id>/          one copy per simulation run, removed after its output is saved

The agent may read the original source before approval. Writing, and running commands, need an approved
plan with permitted edits, and writes are limited to the files that plan permits (AGENTS.md hard rule 4).
"""

from __future__ import annotations

import difflib
import shutil
from pathlib import Path, PurePosixPath

from abc_harness.execution.runner import Runner
from abc_harness.simulators import get_simulator

SCRATCH_PREFIX = "scratch/"


class EditRefused(Exception):
    """A write the approved plan does not permit; the message goes back to the model."""


class Workspace:
    def __init__(self, artifact_dir: Path, runner: Runner) -> None:
        self.root = artifact_dir / "workspace"
        self.runner = runner
        self.images: dict[str, str] = {}  # simulator -> image ID its original source came from

    @property
    def edited_dir(self) -> Path:
        return self.root / "edited"

    @property
    def scratch_dir(self) -> Path:
        return self.root / "scratch"

    def original(self, simulator_name: str, image: str) -> Path:
        """The simulator's source as the image holds it, exported on first use."""
        path = self.root / "original" / simulator_name
        if path.exists():
            if self.images[simulator_name] != image:
                raise EditRefused(f"the workspace holds {simulator_name} source from image {self.images[simulator_name]}, "
                                  f"but the plan pins {image}; start a new task")  # fmt: skip
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.runner.export(image, get_simulator(simulator_name).source_path_in_image, path)
        self.images[simulator_name] = image
        return path

    def edited(self, simulator_name: str, image: str) -> Path:
        """The agent's copy of the original source, created on first use."""
        original = self.original(simulator_name, image)
        if not self.edited_dir.exists():
            shutil.copytree(original, self.edited_dir)
            self.scratch_dir.mkdir(parents=True, exist_ok=True)
        return self.edited_dir

    def target(self, path: str, permitted: list[str]) -> Path:
        """Resolve a write: a permitted source file, or any file under scratch/."""
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise EditRefused(f"{path!r} must be a plain relative path")
        if path.startswith(SCRATCH_PREFIX):
            return self.scratch_dir / path[len(SCRATCH_PREFIX) :]
        if path not in permitted:
            allowed = ", ".join(permitted) or "none"
            raise EditRefused(f"{path} is not a permitted edit of the approved plan (permitted: {allowed}; "
                              f"tests and notes go under {SCRATCH_PREFIX})")  # fmt: skip
        return self.edited_dir / path

    def changed_files(self, simulator_name: str) -> list[str]:
        """Source files that differ between the edited copy and the original: changed, added, or removed."""
        if not self.edited_dir.exists():
            return []
        original = self.root / "original" / simulator_name
        names = {p.relative_to(original).as_posix() for p in original.rglob("*") if p.is_file()}
        names |= {p.relative_to(self.edited_dir).as_posix() for p in self.edited_dir.rglob("*") if p.is_file()}
        changed = []
        for name in sorted(names):
            a, b = original / name, self.edited_dir / name
            if not (a.exists() and b.exists() and a.read_bytes() == b.read_bytes()):
                changed.append(name)
        return changed

    def save_diff(self, simulator_name: str, dest: Path) -> list[str]:
        """Write the full diff of the edited copy against the original. Returns the changed files."""
        original = self.root / "original" / simulator_name
        changed = self.changed_files(simulator_name)
        chunks: list[str] = []
        for name in changed:
            before = _lines(original / name)
            after = _lines(self.edited_dir / name)
            chunks.extend(difflib.unified_diff(before, after, f"a/src/{name}", f"b/src/{name}"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("".join(chunks), encoding="utf-8")
        return changed


def _lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
