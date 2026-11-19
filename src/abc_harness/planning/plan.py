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
from pathlib import Path, PurePosixPath
from typing import Any

from abc_harness.literature.figures import slug
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
OPTIONAL_FIELDS = {"permitted_edits": list, "validation": dict, "execution_image": str, "citations": list}
EDIT_FIELDS = {"path", "purpose"}
VALIDATION_FIELDS = {"description", "params", "seeds", "metric", "expected", "tolerance"}
VALIDATION_CONFIGURATION = "validation"
# A citation rests on a quote, or on a figure reading: a value with its uncertainty read off a figure.
QUOTE_FIELDS = {"paper", "supports", "quote"}
FIGURE_FIELDS = {"paper", "supports", "figure", "reading"}
MAX_QUOTE_CHARS = 600
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
    edited: bool = False  # run the agent-edited source instead of the original


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

    @property
    def permitted_paths(self) -> list[str]:
        """Source files the agent may create or change, relative to the simulator source root."""
        return [e["path"] for e in self.data.get("permitted_edits", [])]

    @property
    def validation(self) -> dict[str, Any] | None:
        return self.data.get("validation")

    def runs(self) -> list[SimulationRunSpec]:
        """Expand configurations x seeds into simulation runs, in a fixed order."""
        specs = []
        for config in self.data["configurations"]:
            params = {**self.data["baseline"], **config.get("params", {})}
            edited = bool(self.permitted_paths) and config.get("edits", True)
            for seed in self.data["seeds"]:
                run_id = f"{config['name']}__seed-{seed}"
                specs.append(SimulationRunSpec(run_id, config["name"], seed, params, edited))
        return specs

    def validation_runs(self) -> list[SimulationRunSpec]:
        """The runs of the validation check, on the edited source; empty when the plan edits nothing."""
        check = self.validation
        if not check:
            return []
        params = {**self.data["baseline"], **check["params"]}
        return [SimulationRunSpec(f"{VALIDATION_CONFIGURATION}__seed-{seed}", VALIDATION_CONFIGURATION, seed, params, True)
                for seed in check["seeds"]]  # fmt: skip

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
            source = ""
            if self.permitted_paths:
                source = " [edited source]" if config.get("edits", True) else " [original source]"
            lines.append(f"  {config['name']}: {shown}{source}")
        lines += [
            "",
            f"Seeds: {', '.join(str(s) for s in d['seeds'])}",
            f"Simulation runs: {len(self.runs())} (timeout {d['run_timeout_seconds']}s each)",
            f"Metrics: {', '.join(d['metrics'])}",
        ]
        if not self.permitted_paths:
            lines.append("Permitted edits beyond parameters and seeds: none")
        else:
            lines += ["", "Permitted edits (the agent may create or change only these files):"]
            lines += [f"  {e['path']}: {e['purpose']}" for e in d["permitted_edits"]]
            check = d["validation"]
            params = ", ".join(f"{k} = {v}" for k, v in check["params"].items()) or "baseline"
            lines += [
                "",
                "Validation check (run by the harness on the edited source before any configuration):",
                f"  {check['description']}",
                f"  parameters: {params}; seeds: {', '.join(str(s) for s in check['seeds'])}",
                f"  passes if the mean {check['metric']} is {check['expected']} ± {check['tolerance']}",
                "  If it fails, the task stops; the agent cannot change this check without a new plan version.",
            ]
        if d.get("citations"):
            lines += ["", "Citations:"]
            for c in d["citations"]:
                if "quote" in c:
                    lines.append(f"  [quote]  {c['paper']} supports {c['supports']}: \"{c['quote']}\"")
                else:
                    lines.append(f"  [figure] {c['paper']} {c['figure']} supports {c['supports']}: {c['reading']} "
                                 "(read off the figure by the model; approximate)")  # fmt: skip
                    lines.append(f"           image: {figure_image_glob(c['paper'], c['figure'])} in the task directory")
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
        if set(config) - {"name", "params", "edits"}:
            raise PlanError(f"configuration {config['name']} has unknown fields")
        if not config["name"].replace("-", "").replace("_", "").isalnum():
            raise PlanError(f"configuration name {config['name']!r} may use only letters, digits, - and _")
        names.append(config["name"])
    if len(set(names)) != len(names):
        raise PlanError("configuration names must be unique")
    if "execution_image" in data and not IMAGE_ID.fullmatch(data["execution_image"]):
        raise PlanError("execution_image must be a full image ID (sha256: followed by 64 hex digits)")
    for citation in data.get("citations", []):
        if not isinstance(citation, dict) or set(citation) not in (QUOTE_FIELDS, FIGURE_FIELDS):
            raise PlanError("each citation needs either paper, supports, quote or paper, supports, figure, reading")
        if not all(isinstance(v, str) and v.strip() for v in citation.values()):
            raise PlanError("citation fields must be non-empty text")
        if len(citation.get("quote", "")) > MAX_QUOTE_CHARS:
            raise PlanError(f"a citation quote may be at most {MAX_QUOTE_CHARS} characters")
        if "reading" in citation and "±" not in citation["reading"]:
            raise PlanError("a figure reading must state its uncertainty with ±, for example '0.954 ± 0.003'")
    simulator = get_simulator(data["simulator"])
    simulator.validate_metrics(data["metrics"])
    for config in data["configurations"]:
        simulator.validate_params({**data["baseline"], **config.get("params", {})})
    _validate_edits(data, simulator)
    return Plan(data)


def _validate_edits(data: dict[str, Any], simulator: Any) -> None:
    """Permitted edits name plain relative files; a plan that edits code must state its validation check."""
    edits = data.get("permitted_edits", [])
    paths = []
    for edit in edits:
        if not isinstance(edit, dict) or set(edit) != EDIT_FIELDS or not all(
            isinstance(edit[f], str) and edit[f].strip() for f in EDIT_FIELDS
        ):
            raise PlanError("each permitted edit needs exactly a path and a purpose")
        path = PurePosixPath(edit["path"])
        if path.is_absolute() or ".." in path.parts or str(path) != edit["path"] or not path.parts:
            raise PlanError(f"permitted edit {edit['path']!r} must be a plain path inside the simulator source")
        paths.append(edit["path"])
    if len(set(paths)) != len(paths):
        raise PlanError("permitted edit paths must be unique")
    for config in data["configurations"]:
        if "edits" in config and (not isinstance(config["edits"], bool) or not edits):
            raise PlanError("a configuration may set edits (true or false) only when the plan has permitted edits")
    check = data.get("validation")
    if not edits:
        if check is not None:
            raise PlanError("a validation check belongs to a plan with permitted edits")
        return
    if not isinstance(check, dict) or set(check) != VALIDATION_FIELDS:
        raise PlanError(f"a plan with permitted edits needs a validation check with {', '.join(sorted(VALIDATION_FIELDS))}")
    if not isinstance(check["description"], str) or not check["description"].strip():
        raise PlanError("the validation check needs a description")
    if not isinstance(check["params"], dict):
        raise PlanError("validation params must be an object")
    seeds = check["seeds"]
    if not isinstance(seeds, list) or not seeds or not all(isinstance(s, int) and not isinstance(s, bool) for s in seeds):
        raise PlanError("validation seeds must be a non-empty list of integers")
    if len(set(seeds)) != len(seeds):
        raise PlanError("validation seeds must be unique")
    numbers = [check["expected"], check["tolerance"]]
    if any(isinstance(n, bool) or not isinstance(n, (int, float)) for n in numbers) or check["tolerance"] <= 0:
        raise PlanError("validation expected must be a number and tolerance a positive number")
    if check["metric"] not in data["metrics"]:
        raise PlanError("the validation metric must be one of the plan's metrics")
    simulator.validate_params({**data["baseline"], **check["params"]})


def figure_image_glob(paper_id: str, label: str) -> str:
    """Where the harness saves a viewed figure, relative to the task's artifact directory."""
    stem = paper_id.removeprefix("arxiv:").replace("/", "_")
    return f"papers/{stem}/figures/{slug(label)}-*"
