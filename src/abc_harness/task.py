"""One task: its artifact directory, plan versions, approved execution, and final artifacts.

`run_task` drives a task from a hand-written plan file. The agent loop in
`agent.py` drives a task from a research question. Both use `Task` for
everything that touches the artifact directory.
"""

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
# ("approve" | "revise" | "reject", comment).
DecideFn = Callable[[Plan], tuple[str, str]]

# Task statuses (docs/project-spec.md "Run and task status").
COMPLETED, PARTIAL, STOPPED, REJECTED, FAILED, NOT_EXECUTED = (
    "completed", "partial", "stopped_by_limit", "rejected", "failed", "not_executed",
)  # fmt: skip


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


class Task:
    def __init__(
        self,
        runner: Runner,
        runs_root: Path = Path("runs"),
        budget: Budget | None = None,
        redact: Callable[[str], str] | None = None,
        **manifest_fields: Any,
    ) -> None:
        self.runner = runner
        self.budget = budget or Budget()
        self.task_id = new_task_id()
        self.artifact_dir = runs_root / self.task_id
        self.artifact_dir.mkdir(parents=True)
        (self.artifact_dir / "plans").mkdir()
        self.trace = Trace(self.artifact_dir / "trace.jsonl", redact=redact)
        self.plans: dict[str, Plan] = {}
        self.executed: Plan | None = None
        self.records: list[RunRecord] = []
        self.summary: str | None = None
        self.started_containers = False
        self.manifest: dict[str, Any] = {
            "task_id": self.task_id,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "harness_version": __version__,
            "python": sys.version.split()[0],
            "host": f"{platform.system()} {platform.machine()}",
            "test_double": getattr(runner, "is_test_double", False),
            **manifest_fields,
        }
        self.trace.event("task_started", task_id=self.task_id, **manifest_fields)

    def add_plan(self, plan: Plan) -> None:
        """Store a proposed plan version under plans/ so every version stays inspectable."""
        self.plans[plan.version] = plan
        path = self.artifact_dir / "plans" / f"{plan.short_version}.json"
        path.write_text(canonical_json(plan.data) + "\n", encoding="utf-8")
        self.trace.event("plan_proposed", plan_version=plan.version, runs=len(plan.runs()))

    def review(self, plan: Plan, decide: DecideFn) -> tuple[str, str]:
        """Show a plan to the researcher, outside the active-runtime budget, and record the decision."""
        self.trace.event("human_wait_started", reason="plan_review", plan_version=plan.version)
        with self.budget.waiting_for_human():
            decision, comment = decide(plan)
        record_decision(self.artifact_dir, plan.version, decision, comment)
        self.trace.event("plan_decision", plan_version=plan.version, decision=decision, comment=comment)
        return decision, comment

    def execute(self, plan: Plan) -> tuple[str, str]:
        """Run every simulation run of an approved plan. Returns (status, stop_reason)."""
        require_approval(self.artifact_dir, plan.version)
        if self.executed is not None:
            raise RuntimeError(f"this task already executed plan {self.executed.short_version}")
        simulator = get_simulator(plan.simulator)
        self.executed = plan
        self.records = [RunRecord(s.run_id, s.configuration, s.seed, s.params) for s in plan.runs()]
        (self.artifact_dir / "plan.json").write_text(canonical_json(plan.data) + "\n", encoding="utf-8")
        self.manifest.update(self.runner.image_info())
        self.manifest.update(plan_version=plan.version, simulator=plan.simulator, command=simulator.command())

        workspace = self.artifact_dir / "workspace"
        workspace.mkdir()
        pristine = workspace / "source"
        self.started_containers = True
        self.runner.export(simulator.source_path_in_image, pristine)
        revision_file = self.artifact_dir / "simulator_revision.txt"
        self.runner.export(simulator.revision_path_in_image, revision_file)
        self.manifest["simulator_revision"] = revision_file.read_text(encoding="utf-8").strip()
        self.trace.event("workspace_prepared", simulator_revision=self.manifest["simulator_revision"])

        try:
            for spec, record in zip(plan.runs(), self.records, strict=True):
                self.budget.check_time()
                require_approval(self.artifact_dir, plan.version)
                self._run_one(spec, record, plan, simulator, pristine)
        except LimitReached as e:
            self.trace.event("limit_reached", limit=e.limit, detail=str(e))
            self.runner.cleanup(self.task_id)
            return STOPPED, str(e)

        completed = sum(r.status == "completed" for r in self.records)
        if completed == len(self.records):
            return COMPLETED, "all planned simulation runs completed"
        if completed:
            return PARTIAL, f"{completed} of {len(self.records)} simulation runs completed"
        return FAILED, "no simulation run completed"

    def _run_one(self, spec: SimulationRunSpec, record: RunRecord, plan: Plan, simulator: Any, pristine: Path) -> None:
        run_dir = self.artifact_dir / "workspace" / "runs" / spec.run_id
        shutil.copytree(pristine, run_dir / "src")
        changed = simulator.apply_params(run_dir / "src", spec.params, spec.seed)
        diff_path = self.artifact_dir / "changes" / f"{spec.run_id}.diff"
        record.diff_file = _save_diff(pristine, run_dir / "src", changed, diff_path)

        timeout = min(plan.run_timeout_seconds, self.budget.remaining_seconds)
        limited_by_budget = timeout < plan.run_timeout_seconds
        self.trace.event("run_started", run_id=spec.run_id, seed=spec.seed, params=spec.params, timeout_seconds=timeout)
        outcome = self.runner.run(self.task_id, spec.run_id, run_dir, simulator.command(), timeout)
        record.exit_code = outcome.exit_code
        record.duration_seconds = round(outcome.duration_seconds, 3)

        raw_dir = self.artifact_dir / "raw" / spec.run_id
        raw_dir.mkdir(parents=True)
        for name, rel in simulator.raw_outputs().items():
            if (run_dir / rel).exists():
                shutil.copyfile(run_dir / rel, raw_dir / name)
                record.raw_files.append(f"raw/{spec.run_id}/{name}")
        shutil.rmtree(run_dir)

        if outcome.timed_out:
            record.status, record.error = "timeout", f"exceeded {timeout:.0f}s"
        elif outcome.exit_code != 0:
            record.status, record.error = "failed", f"exit code {outcome.exit_code}"
        else:
            try:
                record.metrics = simulator.compute_metrics(raw_dir, spec.params)
                record.status = "completed"
            except (SimulatorError, OSError, ValueError) as e:
                record.status, record.error = "failed", f"output did not parse: {e}"
        self.trace.event("run_finished", run_id=spec.run_id, status=record.status, exit_code=record.exit_code,
                         duration_seconds=record.duration_seconds, metrics=record.metrics, error=record.error)  # fmt: skip

        if outcome.timed_out and limited_by_budget:
            raise LimitReached("time", f"active runtime ran out during {spec.run_id}")

    def close(self, status: str, stop_reason: str) -> TaskResult:
        if self.started_containers:
            self.runner.cleanup(self.task_id)
        self.manifest.update(
            status=status,
            stop_reason=stop_reason,
            active_seconds=round(self.budget.active_seconds, 3),
            waiting_seconds=round(self.budget.waiting_seconds, 3),
            limits={"time_limit_seconds": self.budget.time_limit_seconds, "llm_call_limit": self.budget.llm_call_limit},
            llm_calls=self.budget.llm_calls,
            plan_versions=list(self.plans),
        )
        write_json(self.artifact_dir / "manifest.json", self.manifest)
        write_json(self.artifact_dir / "results.json", [asdict(r) for r in self.records])
        plan = self.executed or (list(self.plans.values())[-1] if self.plans else None)
        write_report(self.artifact_dir, plan, self.records, self.manifest, self.summary)
        self.trace.event("task_finished", status=status, stop_reason=stop_reason,
                         active_seconds=self.budget.active_seconds, llm_calls=self.budget.llm_calls)  # fmt: skip
        self.trace.close()
        return TaskResult(self.task_id, self.artifact_dir, status, stop_reason, self.records)


def run_task(
    plan_path: Path,
    runner: Runner,
    decide: DecideFn,
    runs_root: Path = Path("runs"),
    budget: Budget | None = None,
) -> TaskResult:
    """Review and run a hand-written plan file (milestone M1)."""
    plan = load_plan(plan_path)
    task = Task(runner, runs_root, budget, mode="plan_file", plan_file=str(plan_path))
    shutil.copyfile(plan_path, task.artifact_dir / "plan.toml")
    task.add_plan(plan)
    status, stop_reason = FAILED, "unknown"
    try:
        decision, _ = task.review(plan, decide)
        if decision != "approve":
            status, stop_reason = REJECTED, "plan rejected by researcher"
        else:
            status, stop_reason = task.execute(plan)
    except KeyboardInterrupt:
        status, stop_reason = FAILED, "interrupted by researcher"
        raise
    except Exception as e:  # noqa: BLE001 - the report must still be written
        status, stop_reason = FAILED, f"{type(e).__name__}: {e}"
        task.trace.event("error", error=stop_reason)
    finally:
        result = task.close(status, stop_reason)
    return result


def _save_diff(original_root: Path, changed_root: Path, files: list[str], dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    chunks = []
    for rel in files:
        before = (original_root / rel).read_text(encoding="utf-8").splitlines(keepends=True)
        after = (changed_root / rel).read_text(encoding="utf-8").splitlines(keepends=True)
        chunks.extend(difflib.unified_diff(before, after, f"a/src/{rel}", f"b/src/{rel}"))
    dest.write_text("".join(chunks), encoding="utf-8")
    return str(dest.relative_to(dest.parents[1]))
