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


class RunnerError(RuntimeError):
    """Docker could not do what the harness asked (missing image, daemon unreachable, cleanup failed)."""


@dataclass(frozen=True)
class RunOutcome:
    exit_code: int | None
    timed_out: bool
    duration_seconds: float


class Runner(Protocol):
    """What the task orchestration needs from an execution backend. Each simulator has its own image."""

    def image_info(self, image: str) -> dict[str, str]: ...

    def export(self, image: str, image_path: str, dest: Path) -> None: ...

    def run(
        self, image: str, task_id: str, run_id: str, workdir: Path, command: str, timeout_seconds: float
    ) -> RunOutcome: ...

    def cleanup(self, task_id: str) -> None: ...


def docker_cli_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in DOCKER_CLI_ENV_ALLOWLIST}


def _docker(*args: str, check: bool = True, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], env=docker_cli_env(), capture_output=True, text=True, check=check, timeout=timeout
    )


class DockerRunner:
    def __init__(self, cpus: str = "2", memory: str = "4g") -> None:
        self.cpus = cpus
        self.memory = memory

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
