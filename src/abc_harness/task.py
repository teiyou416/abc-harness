"""Runs one task from a plan file: review, approval, simulation runs, and artifacts."""

from __future__ import annotations

import difflib
import platform
import secrets
import shutil
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from abc_harness import __version__
from abc_harness.approval import record_decision, require_approval
from abc_harness.limits import Budget, LimitReached
from abc_harness.plan import Plan, SimulationRunSpec, canonical_json, load_plan
from abc_harness.report import write_json, write_report
from abc_harness.runner import Runner
from abc_harness.simulators import SimulatorError, get_simulator
from abc_harness.trace import Trace

# A decision function shows the plan to the researcher and returns
# ("approve" | "reject", comment).
DecideFn = Callable[[Plan], tuple[str, str]]


@dataclass
class RunRecord:
    run_id: str
    configuration: str
    seed: int
    params: dict[str, Any]
    status: str = "missing"
    exit_code: int | None = None
    duration_seconds: float | None = None
    metrics: dict[str, float] = field(default_factory=dict)
    raw_files: list[str] = field(default_factory=list)
    diff_file: str | None = None
    error: str | None = None


@dataclass
class TaskResult:
    task_id: str
    artifact_dir: Path
    status: str
    stop_reason: str
    runs: list[RunRecord]


def new_task_id() -> str:
    return f"{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}"


def run_task(
    plan_path: Path,
    runner: Runner,
    decide: DecideFn,
    runs_root: Path = Path("runs"),
    budget: Budget | None = None,
) -> TaskResult:
    plan = load_plan(plan_path)
    simulator = get_simulator(plan.simulator)
    budget = budget or Budget()
    task_id = new_task_id()
    artifact_dir = runs_root / task_id
    artifact_dir.mkdir(parents=True)
    trace = Trace(artifact_dir / "trace.jsonl")
    shutil.copyfile(plan_path, artifact_dir / "plan.toml")
    (artifact_dir / "plan.json").write_text(canonical_json(plan.data) + "\n", encoding="utf-8")

    records = [RunRecord(s.run_id, s.configuration, s.seed, s.params) for s in plan.runs()]
    manifest: dict[str, Any] = {
        "task_id": task_id,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "plan_version": plan.version,
        "plan_file": str(plan_path),
        "simulator": plan.simulator,
        "harness_version": __version__,
        "python": sys.version.split()[0],
        "host": f"{platform.system()} {platform.machine()}",
        "test_double": getattr(runner, "is_test_double", False),
    }
    trace.event("task_started", task_id=task_id, plan_version=plan.version, runs_planned=len(records))

    status, stop_reason = "failed", "unknown"
    try:
        trace.event("human_wait_started", reason="plan_review")
        with budget.waiting_for_human():
            decision, comment = decide(plan)
        record_decision(artifact_dir, plan.version, decision, comment)
        trace.event("plan_decision", plan_version=plan.version, decision=decision, comment=comment)

        if decision != "approve":
            status, stop_reason = "rejected", "plan rejected by researcher"
        else:
            status, stop_reason = _execute(plan, simulator, runner, artifact_dir, task_id, records, budget, trace, manifest)
    except KeyboardInterrupt:
        status, stop_reason = "failed", "interrupted by researcher"
        raise
    except Exception as e:  # noqa: BLE001 - the report must still be written
        status, stop_reason = "failed", f"{type(e).__name__}: {e}"
        trace.event("error", error=stop_reason)
    finally:
        if status != "rejected":
            runner.cleanup(task_id)
        manifest.update(
            status=status,
            stop_reason=stop_reason,
            active_seconds=round(budget.active_seconds, 3),
            waiting_seconds=round(budget.waiting_seconds, 3),
            limits={"time_limit_seconds": budget.time_limit_seconds, "llm_call_limit": budget.llm_call_limit},
            llm_calls=budget.llm_calls,
        )
        write_json(artifact_dir / "manifest.json", manifest)
        write_json(artifact_dir / "results.json", [asdict(r) for r in records])
        write_report(artifact_dir, plan, records, manifest)
        trace.event("task_finished", status=status, stop_reason=stop_reason, active_seconds=budget.active_seconds)
        trace.close()
    return TaskResult(task_id, artifact_dir, status, stop_reason, records)


def _execute(
    plan: Plan,
    simulator: Any,
    runner: Runner,
    artifact_dir: Path,
    task_id: str,
    records: list[RunRecord],
    budget: Budget,
    trace: Trace,
    manifest: dict[str, Any],
) -> tuple[str, str]:
    require_approval(artifact_dir, plan.version)
    manifest.update(runner.image_info())
    manifest["command"] = simulator.command()

    workspace = artifact_dir / "workspace"
    workspace.mkdir()
    pristine = workspace / "source"
    runner.export(simulator.source_path_in_image, pristine)
    runner.export(simulator.revision_path_in_image, artifact_dir / "simulator_revision.txt")
    manifest["simulator_revision"] = (artifact_dir / "simulator_revision.txt").read_text(encoding="utf-8").strip()
    trace.event("workspace_prepared", simulator_revision=manifest["simulator_revision"], image=manifest.get("image"))

    try:
        for spec, record in zip(plan.runs(), records, strict=True):
            budget.check_time()
            require_approval(artifact_dir, plan.version)
            _run_one(spec, record, plan, simulator, runner, artifact_dir, pristine, task_id, budget, trace)
    except LimitReached as e:
        trace.event("limit_reached", limit=e.limit, detail=str(e))
        runner.cleanup(task_id)
        return "stopped_by_limit", str(e)

    completed = sum(r.status == "completed" for r in records)
    if completed == len(records):
        return "completed", "all planned simulation runs completed"
    if completed:
        return "partial", f"{completed} of {len(records)} simulation runs completed"
    return "failed", "no simulation run completed"


def _run_one(
    spec: SimulationRunSpec,
    record: RunRecord,
    plan: Plan,
    simulator: Any,
    runner: Runner,
    artifact_dir: Path,
    pristine: Path,
    task_id: str,
    budget: Budget,
    trace: Trace,
) -> None:
    run_dir = artifact_dir / "workspace" / "runs" / spec.run_id
    shutil.copytree(pristine, run_dir / "src")
    changed = simulator.apply_params(run_dir / "src", spec.params, spec.seed)
    record.diff_file = _save_diff(pristine, run_dir / "src", changed, artifact_dir / "changes" / f"{spec.run_id}.diff")

    timeout = min(plan.run_timeout_seconds, budget.remaining_seconds)
    limited_by_budget = timeout < plan.run_timeout_seconds
    trace.event("run_started", run_id=spec.run_id, seed=spec.seed, params=spec.params, timeout_seconds=timeout)
    outcome = runner.run(task_id, spec.run_id, run_dir, simulator.command(), timeout)
    record.exit_code = outcome.exit_code
    record.duration_seconds = round(outcome.duration_seconds, 3)

    raw_dir = artifact_dir / "raw" / spec.run_id
    raw_dir.mkdir(parents=True)
    for name, rel in simulator.raw_outputs().items():
        if (run_dir / rel).exists():
            shutil.copyfile(run_dir / rel, raw_dir / name)
            record.raw_files.append(f"raw/{spec.run_id}/{name}")
    shutil.rmtree(run_dir)

    if outcome.timed_out:
        record.status = "timeout"
        record.error = f"exceeded {timeout:.0f}s"
    elif outcome.exit_code != 0:
        record.status, record.error = "failed", f"exit code {outcome.exit_code}"
    else:
        try:
            record.metrics = simulator.compute_metrics(raw_dir, spec.params)
            record.status = "completed"
        except (SimulatorError, OSError, ValueError) as e:
            record.status, record.error = "failed", f"output did not parse: {e}"
    trace.event("run_finished", run_id=spec.run_id, status=record.status, exit_code=record.exit_code,
                duration_seconds=record.duration_seconds, metrics=record.metrics, error=record.error)  # fmt: skip

    if outcome.timed_out and limited_by_budget:
        raise LimitReached("time", f"active runtime ran out during {spec.run_id}")


def _save_diff(original_root: Path, changed_root: Path, files: list[str], dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    chunks = []
    for rel in files:
        before = (original_root / rel).read_text(encoding="utf-8").splitlines(keepends=True)
        after = (changed_root / rel).read_text(encoding="utf-8").splitlines(keepends=True)
        chunks.extend(difflib.unified_diff(before, after, f"a/src/{rel}", f"b/src/{rel}"))
    dest.write_text("".join(chunks), encoding="utf-8")
    return str(dest.relative_to(dest.parents[1]))
