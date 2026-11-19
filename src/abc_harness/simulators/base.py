"""The interface every simulator adapter implements."""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

# A custom metric is printed by agent-written code as one stdout line, e.g. "ABC_METRIC attacker_share=0.3004".
CUSTOM_METRIC_LINE = re.compile(r"^ABC_METRIC\s+([a-z][a-z0-9_]*)\s*=\s*(\S+)\s*$")


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

    def compute_metrics(
        self, raw_dir: Path, params: dict[str, Any], metrics: Sequence[str] | None = None
    ) -> dict[str, float]:
        """Compute the named built-in metrics (all of them when None); a metric not asked for is never computed,
        so output that one metric cannot use does not fail a run that does not need it."""
        ...


def read_custom_metrics(stdout: Path, names: Sequence[str]) -> dict[str, float]:
    """The value of each custom metric from its last `ABC_METRIC <name>=<value>` line in a run's stdout."""
    found: dict[str, str] = {}
    for line in stdout.read_text(encoding="utf-8", errors="replace").splitlines():
        match = CUSTOM_METRIC_LINE.match(line.strip())
        if match:
            found[match.group(1)] = match.group(2)
    values = {}
    for name in names:
        if name not in found:
            raise SimulatorError(f"the run printed no 'ABC_METRIC {name}=<value>' line")
        try:
            value = float(found[name])
        except ValueError as e:
            raise SimulatorError(f"ABC_METRIC {name} is not a number: {found[name]!r}") from e
        if not math.isfinite(value):
            raise SimulatorError(f"ABC_METRIC {name} is not finite: {found[name]!r}")
        values[name] = value
    return values
