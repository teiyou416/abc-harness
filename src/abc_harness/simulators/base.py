"""The interface every simulator adapter implements."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class SimulatorError(ValueError):
    """Raised for invalid parameters, metrics, or simulator output."""


class Simulator(Protocol):
    name: str
    image_tag: str
    docker_context: Path
    source_path_in_image: str
    revision_path_in_image: str
    supported_metrics: tuple[str, ...]

    def describe(self) -> str:
        """Return the capability card the agent reads before planning."""
        ...

    def validate_params(self, params: dict[str, Any]) -> None: ...

    def validate_metrics(self, metrics: list[str]) -> None: ...

    def apply_params(self, source_dir: Path, params: dict[str, Any], seed: int) -> list[str]:
        """Edit the run's source copy in place and return the relative paths of changed files."""
        ...

    def command(self) -> str:
        """Return the shell command that builds and runs the simulator inside the run directory."""
        ...

    def raw_outputs(self) -> dict[str, str]:
        """Map a saved raw output name to its path relative to the run directory."""
        ...

    def compute_metrics(self, raw_dir: Path, params: dict[str, Any]) -> dict[str, float]: ...
