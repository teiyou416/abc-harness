"""FakeRunner replaces DockerRunner in tests that must not need Docker.

It copies fixture source instead of exporting it from an image, and instead of
starting a container it writes fixture output (or fails, or times out) and
advances an optional fake clock by a fixed number of seconds. Each image tag
points to a fake image ID; `rebuild` points the tag at a new ID, as
`abc-harness image build` would. The tag behind an ID selects the fixture set:
a tag containing "blocksim" gets BlockSim files.

`convert_pdf` stands in for the PDF parser image: it copies a trimmed, recorded
MinerU output (tests/fixtures/pdf/) whatever the PDF says.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from abc_harness.execution.runner import RunnerError, RunOutcome

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _fixtures(tag: str) -> Path:
    return FIXTURES / ("blocksim" if "blocksim" in tag else "simblock")


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FakeRunner:
    """Behaviour per run_id: "complete" (default), "fail", "timeout", or "garbage" output."""

    behaviours: dict[str, str] = field(default_factory=dict)
    clock: FakeClock | None = None
    seconds_per_run: float = 1.0
    is_test_double: bool = True
    runs: list[str] = field(default_factory=list)
    images: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    cleanups: list[str] = field(default_factory=list)
    cleanup_error: str | None = None  # set to make cleanup fail, as with an unreachable Docker daemon
    # sandbox exec: each call is recorded; `sandbox_handler(command, source_dir, scratch_dir)` decides the outcome
    sandbox_calls: list[str] = field(default_factory=list)
    sandbox_handler: Callable[[str, Path, Path], RunOutcome] | None = None
    # called with (run_id, workdir) before a run writes its output, so a test can see which source it got
    inspect: Callable[[str, Path], None] | None = None
    # the PDF parser: "complete" (default), "fail", "timeout", or "garbage"; and the parser run time per PDF
    pdf_behaviour: str = "complete"
    seconds_per_pdf: float = 120.0
    pdf_calls: list[str] = field(default_factory=list)
    missing_images: set[str] = field(default_factory=set)  # tags that are not built
    tags: dict[str, str] = field(default_factory=dict)  # tag -> current image ID
    built: dict[str, str] = field(default_factory=dict)  # every image ID that exists -> its tag

    def rebuild(self, tag: str, remove_old: bool = False) -> str:
        """Point the tag at a new image ID, as rebuilding the image would."""
        old = self._current(tag)
        if remove_old:
            del self.built[old]
        new = "sha256:" + hashlib.sha256(f"{old}-rebuilt".encode()).hexdigest()
        self.tags[tag], self.built[new] = new, tag
        return new

    def _current(self, tag: str) -> str:
        if tag not in self.tags:
            self.tags[tag] = "sha256:" + hashlib.sha256(tag.encode()).hexdigest()
            self.built[self.tags[tag]] = tag
        return self.tags[tag]

    def _tag(self, image: str) -> str:
        return self.built.get(image, image)

    def image_info(self, image: str) -> dict[str, str]:
        if image in self.missing_images:
            raise RunnerError(f"execution image {image} not found")
        if image.startswith("sha256:"):
            if image not in self.built:
                raise RunnerError(f"execution image {image} not found")
            return {"image": image, "image_id": image}
        return {"image": image, "image_id": self._current(image)}

    def export(self, image: str, image_path: str, dest: Path) -> None:
        self.exports.append(image_path)
        if image_path.endswith("REVISION"):
            shutil.copyfile(_fixtures(self._tag(image)) / "REVISION", dest)
        else:
            shutil.copytree(_fixtures(self._tag(image)) / "source", dest)

    def run(
        self, image: str, task_id: str, run_id: str, workdir: Path, command: str, timeout_seconds: float
    ) -> RunOutcome:
        self.runs.append(run_id)
        self.images.append(image)
        if self.inspect:
            self.inspect(run_id, workdir)
        behaviour = self.behaviours.get(run_id, "complete")
        if self.clock:
            self.clock.advance(min(self.seconds_per_run, timeout_seconds))
        if behaviour == "timeout" or self.seconds_per_run > timeout_seconds:
            return RunOutcome(None, True, timeout_seconds)
        if behaviour == "fail":
            return RunOutcome(1, False, self.seconds_per_run)
        if "blocksim" in self._tag(image):
            self._write_blocksim(workdir, behaviour)
        else:
            self._write_simblock(workdir, behaviour)
        return RunOutcome(0, False, self.seconds_per_run)

    def sandbox(
        self, image: str, task_id: str, name: str, source_dir: Path, scratch_dir: Path, command: str,
        timeout_seconds: float,
    ) -> RunOutcome:
        self.sandbox_calls.append(command)
        if self.clock:
            self.clock.advance(min(self.seconds_per_run, timeout_seconds))
        if self.sandbox_handler:
            return self.sandbox_handler(command, source_dir, scratch_dir)
        return RunOutcome(0, False, self.seconds_per_run, f"ran: {command}\n")

    def convert_pdf(
        self, image: str, task_id: str, name: str, pdf: Path, out_dir: Path, timeout_seconds: float
    ) -> RunOutcome:
        self.pdf_calls.append(pdf.name)
        if self.clock:
            self.clock.advance(min(self.seconds_per_pdf, timeout_seconds))
        if self.pdf_behaviour == "timeout" or self.seconds_per_pdf > timeout_seconds:
            return RunOutcome(None, True, timeout_seconds, "parsing...\n")
        if self.pdf_behaviour == "fail":
            return RunOutcome(1, False, self.seconds_per_pdf, "Traceback: the parser crashed\n")
        if self.pdf_behaviour == "garbage":
            (out_dir / "structured_content.json").write_text("not json")
        else:
            shutil.copytree(FIXTURES / "pdf" / "2007.05614", out_dir, dirs_exist_ok=True)
        return RunOutcome(0, False, self.seconds_per_pdf, "Parsed 1 input(s).\nmineru 4.2.3; models fixture\n")

    def cleanup(self, task_id: str) -> None:
        self.cleanups.append(task_id)
        if self.cleanup_error:
            raise RunnerError(self.cleanup_error)

    @staticmethod
    def _write_simblock(workdir: Path, behaviour: str) -> None:
        output_dir = workdir / "src" / "dist" / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        if behaviour == "garbage":
            (workdir / "stdout.txt").write_text("not simblock output\n")
            (output_dir / "blockList.txt").write_text("")
            return
        shutil.copyfile(FIXTURES / "simblock" / "stdout.txt", workdir / "stdout.txt")
        shutil.copyfile(FIXTURES / "simblock" / "blockList.txt", output_dir / "blockList.txt")

    @staticmethod
    def _write_blocksim(workdir: Path, behaviour: str) -> None:
        output_dir = workdir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        (workdir / "stdout.txt").write_text("")
        if behaviour == "garbage":
            (output_dir / "SimOutput.csv").write_text("Total Blocks,Stale Blocks\n")
            return
        for name in ("SimOutput.csv", "Chain.csv"):
            shutil.copyfile(FIXTURES / "blocksim" / "output" / name, output_dir / name)
