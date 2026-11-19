"""Experiment plans: loading, validation, versioning, and display.

A plan version is the SHA-256 of the plan's canonical JSON form. Any change to
the simulator, parameters, seeds, metrics, permitted edits, or execution image
changes the version, so an approval recorded for one version never covers
another. The harness fills `execution_image` with the image ID before the
researcher sees the plan (`Task.pin_image`).
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from abc_harness.simulators import get_simulator

REQUIRED_FIELDS = {
    "title": str,
    "question": str,
    "simulator": str,
    "rationale": str,
    "seeds": list,
    "metrics": list,
    "run_timeout_seconds": int,
    "baseline": dict,
    "configurations": list,
}
OPTIONAL_FIELDS = {"permitted_edits": list, "execution_image": str}
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")


class PlanError(ValueError):
    """Raised when a plan file is malformed."""


@dataclass(frozen=True)
class SimulationRunSpec:
    """One cell of the plan: one configuration with one seed."""

    run_id: str
    configuration: str
    seed: int
    params: dict[str, Any]


@dataclass(frozen=True)
class Plan:
    data: dict[str, Any]

    @property
    def version(self) -> str:
        return hashlib.sha256(canonical_json(self.data).encode("utf-8")).hexdigest()

    @property
    def short_version(self) -> str:
        return self.version[:12]

    @property
    def simulator(self) -> str:
        return self.data["simulator"]

    @property
    def metrics(self) -> list[str]:
        return list(self.data["metrics"])

    @property
    def execution_image(self) -> str | None:
        """The image ID this plan runs in; None until the harness pins it."""
        return self.data.get("execution_image")

    @property
    def run_timeout_seconds(self) -> int:
        return self.data["run_timeout_seconds"]

    def runs(self) -> list[SimulationRunSpec]:
        """Expand configurations x seeds into simulation runs, in a fixed order."""
        specs = []
        for config in self.data["configurations"]:
            params = {**self.data["baseline"], **config.get("params", {})}
            for seed in self.data["seeds"]:
                run_id = f"{config['name']}__seed-{seed}"
                specs.append(SimulationRunSpec(run_id, config["name"], seed, params))
        return specs

    def render(self) -> str:
        """Return the plan as the researcher sees it before deciding."""
        d = self.data
        lines = [
            f"Plan: {d['title']}",
            f"Version: {self.short_version}",
            "",
            f"Question: {d['question']}",
            f"Simulator: {d['simulator']}",
            f"Execution image: {d.get('execution_image', 'not pinned yet')}",
            f"Why this simulator: {d['rationale']}",
            "",
            "Baseline parameters:",
            *(f"  {k} = {v}" for k, v in d["baseline"].items()),
            "",
            "Configurations:",
        ]
        for config in d["configurations"]:
            changes = config.get("params", {})
            shown = ", ".join(f"{k} = {v}" for k, v in changes.items()) or "baseline"
            lines.append(f"  {config['name']}: {shown}")
        lines += [
            "",
            f"Seeds: {', '.join(str(s) for s in d['seeds'])}",
            f"Simulation runs: {len(self.runs())} (timeout {d['run_timeout_seconds']}s each)",
            f"Metrics: {', '.join(d['metrics'])}",
            f"Permitted edits beyond parameters and seeds: {', '.join(d.get('permitted_edits', [])) or 'none'}",
        ]
        return "\n".join(lines)


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def load_plan(path: Path) -> Plan:
    """Load a plan from TOML (hand-written) or JSON (plan.json in an artifact directory)."""
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text) if path.suffix == ".json" else tomllib.loads(text)
    except (tomllib.TOMLDecodeError, json.JSONDecodeError) as e:
        raise PlanError(f"{path}: invalid {path.suffix.lstrip('.').upper() or 'TOML'}: {e}") from e
    if not isinstance(data, dict):
        raise PlanError(f"{path}: a plan must be an object")
    return validate_plan(data)


def validate_plan(data: dict[str, Any]) -> Plan:
    unknown = set(data) - set(REQUIRED_FIELDS) - set(OPTIONAL_FIELDS)
    if unknown:
        raise PlanError(f"unknown plan fields: {', '.join(sorted(unknown))}")
    for field, kind in REQUIRED_FIELDS.items():
        if field not in data:
            raise PlanError(f"missing plan field: {field}")
        if not isinstance(data[field], kind):
            raise PlanError(f"plan field {field} must be {kind.__name__}")
    if not data["seeds"] or not all(isinstance(s, int) and not isinstance(s, bool) for s in data["seeds"]):
        raise PlanError("seeds must be a non-empty list of integers")
    if len(set(data["seeds"])) != len(data["seeds"]):
        raise PlanError("seeds must be unique")
    if data["run_timeout_seconds"] <= 0:
        raise PlanError("run_timeout_seconds must be positive")
    if not data["configurations"]:
        raise PlanError("configurations must not be empty")
    names = []
    for config in data["configurations"]:
        if not isinstance(config, dict) or not isinstance(config.get("name"), str):
            raise PlanError("each configuration needs a name")
        if set(config) - {"name", "params"}:
            raise PlanError(f"configuration {config['name']} has unknown fields")
        if not config["name"].replace("-", "").replace("_", "").isalnum():
            raise PlanError(f"configuration name {config['name']!r} may use only letters, digits, - and _")
        names.append(config["name"])
    if len(set(names)) != len(names):
        raise PlanError("configuration names must be unique")
    if "execution_image" in data and not IMAGE_ID.fullmatch(data["execution_image"]):
        raise PlanError("execution_image must be a full image ID (sha256: followed by 64 hex digits)")
    if data.get("permitted_edits"):
        raise PlanError("permitted_edits is not supported until milestone M5")

    simulator = get_simulator(data["simulator"])
    simulator.validate_metrics(data["metrics"])
    for config in data["configurations"]:
        simulator.validate_params({**data["baseline"], **config.get("params", {})})
    return Plan(data)
