"""Executes simulation runs inside the execution image (AGENTS.md hard rules 4, 5, 7).

It also runs the PDF parser image, one container per PDF, and the plot image,
one container per figure script, under the same rules. The parser gets more
CPU and memory than a simulation because MinerU needs about 5 GB for a
20-page paper.

Every container runs with no network, CPU and memory limits, no environment
variables from the host, and a label that names its task. Cleanup removes
every container carrying that label, so a timeout or a limit never leaves a
simulator running.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

TASK_LABEL = "org.abc-harness.task"
CONTAINER_WORKDIR = "/work"
# The docker CLI itself needs these to find its daemon and config. Nothing
# else from the host environment reaches the CLI, and no variable at all is
# forwarded into a container.
DOCKER_CLI_ENV_ALLOWLIST = ("PATH", "HOME", "DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH")


class RunnerError(RuntimeError):
    """Docker could not do what the harness asked (missing image, daemon unreachable, cleanup failed)."""


@dataclass(frozen=True)
class RunOutcome:
    exit_code: int | None
    timed_out: bool
    duration_seconds: float
    output: str = ""  # combined stdout and stderr; filled by sandbox exec only


SANDBOX_SOURCE = "/work/src"  # the edited source, read-only
SANDBOX_SCRATCH = "/work/scratch"  # writable; the working directory
MAX_SANDBOX_OUTPUT = 200_000
PLOT_DATA = "/data"  # the task's results, read-only
PLOT_SCRIPT = "/work/figure.py"  # read-only
PLOT_OUTPUT = "/out"  # writable; the working directory
PDF_INPUT = "/in/paper.pdf"  # read-only
PDF_OUTPUT = "/out"  # writable; receives structured_content.json and images/
# Parse to a zip, unpack it inside the container (zipfile drops absolute and ".." paths), and keep only what
# the harness reads plus the Markdown for people.
PDF_COMMAND = (
    f"mineru-kit parse {PDF_INPUT} -o {PDF_OUTPUT}/paper.zip --format zip --tier basic"
    f" && python -c \"import zipfile; zipfile.ZipFile('{PDF_OUTPUT}/paper.zip').extractall('{PDF_OUTPUT}')\""
    f" && rm -f {PDF_OUTPUT}/paper.zip {PDF_OUTPUT}/middle_json.json"
    " && cat /opt/mineru/REVISION"
)


class Runner(Protocol):
    """What the task orchestration needs from an execution backend. Each simulator has its own image."""

    def image_info(self, image: str) -> dict[str, str]: ...

    def export(self, image: str, image_path: str, dest: Path) -> None: ...

    def run(
        self, image: str, task_id: str, run_id: str, workdir: Path, command: str, timeout_seconds: float
    ) -> RunOutcome: ...

    def sandbox(
        self, image: str, task_id: str, name: str, source_dir: Path, scratch_dir: Path, command: str,
        timeout_seconds: float,
    ) -> RunOutcome: ...

    def convert_pdf(self, image: str, task_id: str, name: str, pdf: Path, out_dir: Path,
                    timeout_seconds: float) -> RunOutcome: ...

    def plot(self, image: str, task_id: str, name: str, data: list[Path], script: Path, out_dir: Path,
             timeout_seconds: float) -> RunOutcome: ...

    def cleanup(self, task_id: str) -> None: ...


def docker_cli_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in DOCKER_CLI_ENV_ALLOWLIST}


def _docker(*args: str, check: bool = True, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], env=docker_cli_env(), capture_output=True, text=True, check=check, timeout=timeout
    )


class DockerRunner:
    def __init__(self, cpus: str = "2", memory: str = "4g", pdf_cpus: str = "6", pdf_memory: str = "6g") -> None:
        self.cpus = cpus
        self.memory = memory
        self.pdf_cpus = pdf_cpus
        self.pdf_memory = pdf_memory

    def image_info(self, image: str) -> dict[str, str]:
        result = _docker("image", "inspect", image, "--format", "{{.Id}}", check=False)
        if result.returncode != 0:
            raise RunnerError(f"execution image {image} not found; run `abc-harness image build` first")
        return {"image": image, "image_id": result.stdout.strip()}

    def export(self, image: str, image_path: str, dest: Path) -> None:
        """Copy a path out of the image without starting it."""
        container_id = _docker("create", image).stdout.strip()
        try:
            _docker("cp", f"{container_id}:{image_path}", str(dest))
        finally:
            _docker("rm", "-f", container_id, check=False)

    def run(
        self, image: str, task_id: str, run_id: str, workdir: Path, command: str, timeout_seconds: float
    ) -> RunOutcome:
        name = f"abc-{task_id}-{run_id}".replace("__", "-")
        args = [
            "run", "--rm", "--name", name,
            "--label", f"{TASK_LABEL}={task_id}",
            "--network", "none",
            "--cpus", self.cpus, "--memory", self.memory,
            "-v", f"{workdir.resolve()}:{CONTAINER_WORKDIR}",
            "-w", CONTAINER_WORKDIR,
            image, "sh", "-c", command,
        ]  # fmt: skip
        started = time.monotonic()
        try:
            result = _docker(*args, check=False, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _docker("rm", "-f", name, check=False)
            return RunOutcome(None, True, time.monotonic() - started)
        return RunOutcome(result.returncode, False, time.monotonic() - started)

    def sandbox(
        self, image: str, task_id: str, name: str, source_dir: Path, scratch_dir: Path, command: str,
        timeout_seconds: float,
    ) -> RunOutcome:
        """Sandbox exec: run the agent's command with the edited source read-only and scratch writable."""
        container = f"abc-{task_id}-{name}"
        args = [
            "run", "--rm", "--name", container,
            "--label", f"{TASK_LABEL}={task_id}",
            "--network", "none",
            "--cpus", self.cpus, "--memory", self.memory,
            "-v", f"{source_dir.resolve()}:{SANDBOX_SOURCE}:ro",
            "-v", f"{scratch_dir.resolve()}:{SANDBOX_SCRATCH}",
            "-w", SANDBOX_SCRATCH,
            image, "sh", "-c", command,
        ]  # fmt: skip
        return self._run_capturing(args, container, timeout_seconds)

    def convert_pdf(self, image: str, task_id: str, name: str, pdf: Path, out_dir: Path,
                    timeout_seconds: float) -> RunOutcome:
        """Parse one PDF with the PDF parser image: the PDF read-only, the output directory writable."""
        container = f"abc-{task_id}-{name}"
        args = [
            "run", "--rm", "--name", container,
            "--label", f"{TASK_LABEL}={task_id}",
            "--network", "none",
            "--cpus", self.pdf_cpus, "--memory", self.pdf_memory,
            "-v", f"{pdf.resolve()}:{PDF_INPUT}:ro",
            "-v", f"{out_dir.resolve()}:{PDF_OUTPUT}",
            image, "sh", "-c", PDF_COMMAND,
        ]  # fmt: skip
        return self._run_capturing(args, container, timeout_seconds)

    def plot(self, image: str, task_id: str, name: str, data: list[Path], script: Path, out_dir: Path,
             timeout_seconds: float) -> RunOutcome:
        """Run one figure script: each data file or folder read-only under /data, only out_dir writable."""
        container = f"abc-{task_id}-{name}"
        mounts = [arg for path in data for arg in ("-v", f"{path.resolve()}:{PLOT_DATA}/{path.name}:ro")]
        args = [
            "run", "--rm", "--name", container,
            "--label", f"{TASK_LABEL}={task_id}",
            "--network", "none",
            "--cpus", self.cpus, "--memory", self.memory,
            *mounts,
            "-v", f"{script.resolve()}:{PLOT_SCRIPT}:ro",
            "-v", f"{out_dir.resolve()}:{PLOT_OUTPUT}",
            "-w", PLOT_OUTPUT,
            image, "python", PLOT_SCRIPT,
        ]  # fmt: skip
        return self._run_capturing(args, container, timeout_seconds)

    def _run_capturing(self, args: list[str], container: str, timeout_seconds: float) -> RunOutcome:
        started = time.monotonic()
        try:
            result = subprocess.run(["docker", *args], env=docker_cli_env(), stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, errors="replace", timeout=timeout_seconds,
                                    check=False)  # fmt: skip
        except subprocess.TimeoutExpired as e:
            _docker("rm", "-f", container, check=False)
            partial = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            return RunOutcome(None, True, time.monotonic() - started, partial[-MAX_SANDBOX_OUTPUT:])
        return RunOutcome(result.returncode, False, time.monotonic() - started, result.stdout[-MAX_SANDBOX_OUTPUT:])

    def cleanup(self, task_id: str) -> None:
        """Remove every container of the task. Raises RunnerError if that cannot be confirmed."""
        listed = _docker("ps", "-aq", "--filter", f"label={TASK_LABEL}={task_id}", check=False)
        if listed.returncode != 0:
            raise RunnerError(f"could not list the task's containers: {listed.stderr.strip()}")
        ids = listed.stdout.split()
        if ids:
            removed = _docker("rm", "-f", *ids, check=False)
            if removed.returncode != 0:
                raise RunnerError(f"could not remove containers {', '.join(ids)}: {removed.stderr.strip()}")


def build_image(context: Path, tag: str) -> str:
    """Build the execution image and return its image ID."""
    subprocess.run(["docker", "build", "-t", tag, str(context)], env=docker_cli_env(), check=True)
    return _docker("image", "inspect", tag, "--format", "{{.Id}}").stdout.strip()


def running_containers(task_id: str) -> list[str]:
    return _docker("ps", "-q", "--filter", f"label={TASK_LABEL}={task_id}", check=False).stdout.split()
