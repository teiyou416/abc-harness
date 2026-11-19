"""One task: its artifact directory, plan versions, approved execution, and final artifacts.

`run_task` drives a task from a hand-written plan file. The agent loop in
`agent.py` drives a task from a research question. Both use `Task` for
everything that touches the artifact directory.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import platform
import secrets
import shutil
import statistics
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from abc_harness import __version__
from abc_harness.execution.limits import Budget, LimitReached
from abc_harness.execution.report import write_json, write_report
from abc_harness.execution.runner import Runner, RunnerError, RunOutcome
from abc_harness.execution.trace import Trace
from abc_harness.execution.workspace import Workspace
from abc_harness.literature.pdf import (
    OUTPUT_FILE,
    PARSE_TIMEOUT_SECONDS,
    PARSER_IMAGE,
    ParseInfo,
    PdfError,
    figure_images,
)
from abc_harness.planning.approval import NotApproved, read_decisions, record_decision, require_approval
from abc_harness.planning.plan import Plan, SimulationRunSpec, canonical_json, load_plan
from abc_harness.simulators import SimulatorError, get_simulator

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
        pdf_cache: Path | None = None,
        **manifest_fields: Any,
    ) -> None:
        self.runner = runner
        # Parsed PDFs, keyed by parser image and PDF content, shared by all tasks under runs_root.
        self.pdf_cache = pdf_cache or runs_root / ".cache" / "pdf"
        self.pdf_parses: list[dict[str, Any]] = []
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
        self.validation_records: list[RunRecord] = []
        self.validation: dict[str, Any] | None = None
        self.sandbox_calls = 0
        self.workspace = Workspace(self.artifact_dir, runner)
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

    def pin_image(self, plan: Plan) -> Plan:
        """Fix the execution image by ID, so the plan version, and with it the approval, covers the image.

        A plan without `execution_image` gets the ID the simulator's image tag points to now. A plan that
        already names one (for example a plan.json from an earlier task) keeps it if that image still exists.
        Raises RunnerError when the image is missing.
        """
        image = plan.execution_image or get_simulator(plan.simulator).image_tag
        image_id = self.runner.image_info(image)["image_id"]
        return Plan({**plan.data, "execution_image": image_id})

    def approved_plan(self) -> Plan | None:
        """The plan version the researcher's latest decision approved, if that decision was an approval."""
        decisions = read_decisions(self.artifact_dir)
        if not decisions or decisions[-1].decision != "approve":
            return None
        return self.plans.get(decisions[-1].plan_version)

    def original_source(self, simulator_name: str) -> Path:
        """The simulator source for reading, exported from the image its tag points to now."""
        image = self.runner.image_info(get_simulator(simulator_name).image_tag)["image_id"]
        self.started_containers = True
        return self.workspace.original(simulator_name, image)

    def sandbox(self, plan: Plan, command: str, timeout_seconds: float) -> tuple[RunOutcome, str]:
        """Sandbox exec for an approved plan with permitted edits. Returns (outcome, saved log path)."""
        require_approval(self.artifact_dir, plan.version)
        assert plan.execution_image is not None and plan.permitted_paths
        edited = self.workspace.edited(plan.simulator, plan.execution_image)
        self.sandbox_calls += 1
        name = f"sandbox-{self.sandbox_calls}"
        timeout = min(timeout_seconds, self.budget.remaining_seconds)
        self.started_containers = True
        self.trace.event("sandbox_started", call=self.sandbox_calls, command=command, timeout_seconds=timeout)
        outcome = self.runner.sandbox(plan.execution_image, self.task_id, name, edited, self.workspace.scratch_dir,
                                      command, timeout)  # fmt: skip
        log = Path("sandbox") / f"{self.sandbox_calls:03d}.log"
        (self.artifact_dir / log).parent.mkdir(exist_ok=True)
        status = "timed out" if outcome.timed_out else f"exit code {outcome.exit_code}"
        (self.artifact_dir / log).write_text(f"$ {command}\n{outcome.output}\n[{status}, "
                                             f"{outcome.duration_seconds:.1f}s]\n", encoding="utf-8")  # fmt: skip
        self.trace.event("sandbox_finished", call=self.sandbox_calls, exit_code=outcome.exit_code,
                         timed_out=outcome.timed_out, duration_seconds=round(outcome.duration_seconds, 3),
                         log=str(log), output_tail=outcome.output[-2000:])  # fmt: skip
        if outcome.timed_out and timeout < timeout_seconds:
            raise LimitReached("time", f"active runtime ran out during sandbox command {self.sandbox_calls}")
        return outcome, str(log)

    def convert_pdf(self, pdf: Path, out_dir: Path) -> ParseInfo:
        """Parse a PDF with the PDF parser image, or reuse an earlier parse of the same bytes by the same image.

        The parse runs outside the active-runtime budget, under its own timeout. Raises PdfError.
        """
        try:
            image_id = self.runner.image_info(PARSER_IMAGE)["image_id"]
        except RunnerError as e:
            raise PdfError(f"the PDF parser image {PARSER_IMAGE} is missing; run `abc-harness image build`") from e
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
        cache = self.pdf_cache / image_id.removeprefix("sha256:")[:16] / digest
        rel_pdf = _relative(pdf, self.artifact_dir)
        if (cache / "parse.json").exists():
            shutil.copytree(cache, out_dir, dirs_exist_ok=True)
            meta = json.loads((cache / "parse.json").read_text(encoding="utf-8"))
            info = ParseInfo(image_id, meta["revision"], meta["seconds"], True, digest)
        else:
            info = self._parse_pdf(pdf, rel_pdf, out_dir, image_id, digest)
            _store_in_cache(out_dir, cache)
        record = {"pdf": rel_pdf, "sha256": digest, "image_id": image_id, "revision": info.revision,
                  "seconds": round(info.seconds, 3), "cached": info.cached}  # fmt: skip
        self.pdf_parses.append(record)
        self.trace.event("pdf_parse_finished", **record)
        return info

    def _parse_pdf(self, pdf: Path, rel_pdf: str, out_dir: Path, image_id: str, digest: str) -> ParseInfo:
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f"pdf-{len(self.pdf_parses) + 1}"
        self.started_containers = True
        self.trace.event("pdf_parse_started", pdf=rel_pdf, sha256=digest, image_id=image_id,
                         timeout_seconds=PARSE_TIMEOUT_SECONDS)  # fmt: skip
        with self.budget.parsing_pdf():
            outcome = self.runner.convert_pdf(image_id, self.task_id, name, pdf, out_dir, PARSE_TIMEOUT_SECONDS)
        (out_dir / "parser.log").write_text(outcome.output, encoding="utf-8")
        log = _relative(out_dir / "parser.log", self.artifact_dir)
        error = None
        if outcome.timed_out:
            error = f"the PDF parser did not finish within {PARSE_TIMEOUT_SECONDS // 60} minutes"
        elif outcome.exit_code != 0 or not (out_dir / OUTPUT_FILE).exists():
            error = f"the PDF parser failed (exit code {outcome.exit_code}); see task/{log}"
        if error:
            self.trace.event("pdf_parse_failed", pdf=rel_pdf, error=error,
                             seconds=round(outcome.duration_seconds, 3))  # fmt: skip
            raise PdfError(error)
        try:
            keep = figure_images(json.loads((out_dir / OUTPUT_FILE).read_text(encoding="utf-8")))
        except (ValueError, AttributeError) as e:
            raise PdfError(f"the PDF parser wrote unreadable output: {e}") from e
        for image in (out_dir / "images").glob("*") if (out_dir / "images").is_dir() else []:
            if f"images/{image.name}" not in keep:
                image.unlink()
        revision = next((line for line in reversed(outcome.output.splitlines()) if line.startswith("mineru ")),
                        "unknown")  # fmt: skip
        meta = {"image_id": image_id, "revision": revision, "seconds": round(outcome.duration_seconds, 3),
                "pdf_sha256": digest}  # fmt: skip
        (out_dir / "parse.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return ParseInfo(image_id, revision, outcome.duration_seconds, False, digest)

    def add_plan(self, plan: Plan) -> None:
        """Store a proposed plan version under plans/ so every version stays inspectable."""
        self.plans[plan.version] = plan
        path = self.artifact_dir / "plans" / f"{plan.short_version}.json"
        path.write_text(canonical_json(plan.data) + "\n", encoding="utf-8")
        self.trace.event("plan_proposed", plan_version=plan.version, runs=len(plan.runs()),
                         execution_image=plan.execution_image)  # fmt: skip

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
        image = plan.execution_image
        if image is None:
            raise NotApproved("the plan names no execution image; the harness pins one before review")
        try:
            self.runner.image_info(image)
        except RunnerError as e:
            raise NotApproved(f"the approved execution image {image} is no longer available; "
                              "propose a new plan version for the current image") from e  # fmt: skip
        self.started_containers = True
        original = self.workspace.original(plan.simulator, image)
        edited = None
        if plan.permitted_paths:
            edited = self.workspace.edited(plan.simulator, image)
            outside = [f for f in self.workspace.changed_files(plan.simulator) if f not in plan.permitted_paths]
            if outside:
                raise NotApproved(f"the edited source changes files the approved plan does not permit: "
                                  f"{', '.join(outside)}")  # fmt: skip
        self.executed = plan
        self.records = [RunRecord(s.run_id, s.configuration, s.seed, s.params) for s in plan.runs()]
        (self.artifact_dir / "plan.json").write_text(canonical_json(plan.data) + "\n", encoding="utf-8")
        self.manifest.update(image=simulator.image_tag, image_id=image)
        self.manifest.update(plan_version=plan.version, simulator=plan.simulator, command=simulator.command())
        if edited is not None:
            changed = self.workspace.save_diff(plan.simulator, self.artifact_dir / "changes" / "edits.diff")
            self.manifest["edited_files"] = changed
            self.trace.event("edits_frozen", files=changed)
        revision_file = self.artifact_dir / "simulator_revision.txt"
        self.runner.export(image, simulator.revision_path_in_image, revision_file)
        self.manifest["simulator_revision"] = revision_file.read_text(encoding="utf-8").strip()
        self.trace.event("workspace_prepared", simulator_revision=self.manifest["simulator_revision"])

        try:
            if edited is not None:
                failure = self._validate(plan, simulator, edited)
                if failure:
                    return FAILED, failure
            for spec, record in zip(plan.runs(), self.records, strict=True):
                self.budget.check_time()
                require_approval(self.artifact_dir, plan.version)
                base = edited if spec.edited and edited is not None else original
                self._run_one(spec, record, plan, simulator, base)
        except LimitReached as e:
            self.trace.event("limit_reached", limit=e.limit, detail=str(e))
            self._cleanup()
            return STOPPED, str(e)

        completed = sum(r.status == "completed" for r in self.records)
        if completed == len(self.records):
            return COMPLETED, "all planned simulation runs completed"
        if completed:
            return PARTIAL, f"{completed} of {len(self.records)} simulation runs completed"
        return FAILED, "no simulation run completed"

    def _validate(self, plan: Plan, simulator: Any, edited: Path) -> str | None:
        """Run the plan's validation check on the edited source. Returns why it failed, or None if it passed."""
        check = plan.validation
        assert check is not None
        specs = plan.validation_runs()
        self.validation_records = [RunRecord(s.run_id, s.configuration, s.seed, s.params) for s in specs]
        for spec, record in zip(specs, self.validation_records, strict=True):
            self.budget.check_time()
            require_approval(self.artifact_dir, plan.version)
            self._run_one(spec, record, plan, simulator, edited)
        values = [r.metrics[check["metric"]] for r in self.validation_records if r.status == "completed"]
        mean = statistics.fmean(values) if values else None
        complete = len(values) == len(specs)
        passed = complete and mean is not None and abs(mean - check["expected"]) <= check["tolerance"]
        self.validation = {"passed": passed, "metric": check["metric"], "mean": mean, "n": len(values),
                           "planned": len(specs), "expected": check["expected"], "tolerance": check["tolerance"],
                           "runs": [asdict(r) for r in self.validation_records]}  # fmt: skip
        write_json(self.artifact_dir / "validation.json", self.validation)
        self.manifest["validation_passed"] = passed
        self.trace.event("validation_finished", passed=passed, mean=mean, n=len(values),
                         expected=check["expected"], tolerance=check["tolerance"])  # fmt: skip
        if passed:
            return None
        if not complete:
            return (f"validation check failed: only {len(values)} of {len(specs)} validation runs completed; "
                    "no configuration was run")  # fmt: skip
        return (f"validation check failed: mean {check['metric']} {mean:.6g} is outside "
                f"{check['expected']} ± {check['tolerance']}; no configuration was run")  # fmt: skip

    def _run_one(self, spec: SimulationRunSpec, record: RunRecord, plan: Plan, simulator: Any, base: Path) -> None:
        run_dir = self.artifact_dir / "workspace" / "runs" / spec.run_id
        shutil.copytree(base, run_dir / "src")
        changed = simulator.apply_params(run_dir / "src", spec.params, spec.seed)
        diff_path = self.artifact_dir / "changes" / f"{spec.run_id}.diff"
        record.diff_file = _save_diff(base, run_dir / "src", changed, diff_path)

        timeout = min(plan.run_timeout_seconds, self.budget.remaining_seconds)
        limited_by_budget = timeout < plan.run_timeout_seconds
        self.trace.event("run_started", run_id=spec.run_id, seed=spec.seed, params=spec.params, timeout_seconds=timeout)
        image = plan.execution_image
        assert image is not None
        outcome = self.runner.run(image, self.task_id, spec.run_id, run_dir, simulator.command(), timeout)
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

    def _cleanup(self) -> None:
        """Remove the task's containers. A failure is recorded, never raised, so the results still get written."""
        try:
            self.runner.cleanup(self.task_id)
        except Exception as e:  # noqa: BLE001 - partial results must survive a broken Docker daemon
            error = f"{type(e).__name__}: {e}"
            self.manifest["cleanup_error"] = error
            self.trace.event("cleanup_failed", error=error)

    def close(self, status: str, stop_reason: str) -> TaskResult:
        if self.started_containers:
            self._cleanup()
        self.manifest.update(
            status=status,
            stop_reason=stop_reason,
            active_seconds=round(self.budget.active_seconds, 3),
            waiting_seconds=round(self.budget.waiting_seconds, 3),
            pdf_parse_seconds=round(self.budget.parsing_seconds, 3),
            pdf_parses=self.pdf_parses,
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
    on_start: Callable[[Path], None] | None = None,
) -> TaskResult:
    """Review and run a hand-written plan file (milestone M1)."""
    plan = load_plan(plan_path)
    task = Task(runner, runs_root, budget, mode="plan_file", plan_file=str(plan_path))
    if on_start:
        on_start(task.artifact_dir)
    shutil.copyfile(plan_path, task.artifact_dir / "plan.toml")
    status, stop_reason = FAILED, "unknown"
    try:
        plan = task.pin_image(plan)
        task.add_plan(plan)
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


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _store_in_cache(out_dir: Path, cache: Path) -> None:
    """Copy a finished parse into the cache. Another task may store the same parse first; either copy is fine."""
    staging = cache.with_name(f".{cache.name}.{secrets.token_hex(4)}")
    shutil.copytree(out_dir, staging)
    try:
        staging.rename(cache)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)


def _save_diff(original_root: Path, changed_root: Path, files: list[str], dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    chunks = []
    for rel in files:
        before = (original_root / rel).read_text(encoding="utf-8").splitlines(keepends=True)
        after = (changed_root / rel).read_text(encoding="utf-8").splitlines(keepends=True)
        chunks.extend(difflib.unified_diff(before, after, f"a/src/{rel}", f"b/src/{rel}"))
    dest.write_text("".join(chunks), encoding="utf-8")
    return str(dest.relative_to(dest.parents[1]))
