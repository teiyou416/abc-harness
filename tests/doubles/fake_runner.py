"""FakeRunner replaces DockerRunner in tests that must not need Docker.

It copies fixture source instead of exporting it from an image, and instead of
starting a container it writes fixture output (or fails, or times out) and
advances an optional fake clock by a fixed number of seconds. The image name
selects the fixture set: an image containing "blocksim" gets BlockSim files.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from abc_harness.runner import RunOutcome

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _fixtures(image: str) -> Path:
    return FIXTURES / ("blocksim" if "blocksim" in image else "simblock")


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

    def image_info(self, image: str) -> dict[str, str]:
        return {"image": f"fake:{image}", "image_id": "sha256:fake"}

    def export(self, image: str, image_path: str, dest: Path) -> None:
        self.exports.append(image_path)
        if image_path.endswith("REVISION"):
            shutil.copyfile(_fixtures(image) / "REVISION", dest)
        else:
            shutil.copytree(_fixtures(image) / "source", dest)

    def run(
        self, image: str, task_id: str, run_id: str, workdir: Path, command: str, timeout_seconds: float
    ) -> RunOutcome:
        self.runs.append(run_id)
        self.images.append(image)
        behaviour = self.behaviours.get(run_id, "complete")
        if self.clock:
            self.clock.advance(min(self.seconds_per_run, timeout_seconds))
        if behaviour == "timeout" or self.seconds_per_run > timeout_seconds:
            return RunOutcome(None, True, timeout_seconds)
        if behaviour == "fail":
            return RunOutcome(1, False, self.seconds_per_run)
        if "blocksim" in image:
            self._write_blocksim(workdir, behaviour)
        else:
            self._write_simblock(workdir, behaviour)
        return RunOutcome(0, False, self.seconds_per_run)

    def cleanup(self, task_id: str) -> None:
        self.cleanups.append(task_id)

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
