"""Executes simulation runs inside the execution image (AGENTS.md hard rules 4, 5, 7).

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


@dataclass(frozen=True)
class RunOutcome:
    exit_code: int | None
    timed_out: bool
    duration_seconds: float


class Runner(Protocol):
    """What the task orchestration needs from an execution backend."""

    def image_info(self) -> dict[str, str]: ...

    def export(self, image_path: str, dest: Path) -> None: ...

    def run(self, task_id: str, run_id: str, workdir: Path, command: str, timeout_seconds: float) -> RunOutcome: ...

    def cleanup(self, task_id: str) -> None: ...


def docker_cli_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in DOCKER_CLI_ENV_ALLOWLIST}


def _docker(*args: str, check: bool = True, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], env=docker_cli_env(), capture_output=True, text=True, check=check, timeout=timeout
    )


class DockerRunner:
    def __init__(self, image: str, cpus: str = "2", memory: str = "4g") -> None:
        self.image = image
        self.cpus = cpus
        self.memory = memory

    def image_info(self) -> dict[str, str]:
        result = _docker("image", "inspect", self.image, "--format", "{{.Id}}", check=False)
        if result.returncode != 0:
            raise RuntimeError(f"execution image {self.image} not found; run `abc-harness image build` first")
        return {"image": self.image, "image_id": result.stdout.strip()}

    def export(self, image_path: str, dest: Path) -> None:
        """Copy a path out of the image without starting it."""
        container_id = _docker("create", self.image).stdout.strip()
        try:
            _docker("cp", f"{container_id}:{image_path}", str(dest))
        finally:
            _docker("rm", "-f", container_id, check=False)

    def run(self, task_id: str, run_id: str, workdir: Path, command: str, timeout_seconds: float) -> RunOutcome:
        name = f"abc-{task_id}-{run_id}".replace("__", "-")
        args = [
            "run", "--rm", "--name", name,
            "--label", f"{TASK_LABEL}={task_id}",
            "--network", "none",
            "--cpus", self.cpus, "--memory", self.memory,
            "-v", f"{workdir.resolve()}:{CONTAINER_WORKDIR}",
            "-w", CONTAINER_WORKDIR,
            self.image, "sh", "-c", command,
        ]  # fmt: skip
        started = time.monotonic()
        try:
            result = _docker(*args, check=False, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _docker("rm", "-f", name, check=False)
            return RunOutcome(None, True, time.monotonic() - started)
        return RunOutcome(result.returncode, False, time.monotonic() - started)

    def cleanup(self, task_id: str) -> None:
        ids = _docker("ps", "-aq", "--filter", f"label={TASK_LABEL}={task_id}", check=False).stdout.split()
        if ids:
            _docker("rm", "-f", *ids, check=False)


def build_image(context: Path, tag: str) -> str:
    """Build the execution image and return its image ID."""
    subprocess.run(["docker", "build", "-t", tag, str(context)], env=docker_cli_env(), check=True)
    return _docker("image", "inspect", tag, "--format", "{{.Id}}").stdout.strip()


def running_containers(task_id: str) -> list[str]:
    return _docker("ps", "-q", "--filter", f"label={TASK_LABEL}={task_id}", check=False).stdout.split()
