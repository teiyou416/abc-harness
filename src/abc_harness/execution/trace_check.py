"""Audit a saved task without executing its code, calling a model, or rewriting its artifacts."""
from __future__ import annotations

import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

from abc_harness.execution import recompute
from abc_harness.execution.report import format_value
from abc_harness.execution.trace import read_trace
from abc_harness.planning.approval import read_decisions
from abc_harness.planning.plan import Plan, SimulationRunSpec, load_plan


class Findings:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.status: set[str] = set()

    def add(self, status: str, message: str) -> None:
        self.status.add(status)
        self.lines.append(f"{status}: {message}")


def _order(root: Path, plan: Plan | None, events: list[dict[str, Any]], findings: Findings) -> set[str]:
    decisions = [(d.plan_version, d.decision) for d in read_decisions(root)]
    traced: list[tuple[str, str]] = []
    starts: set[str] = set()
    unversioned = 0
    version = plan.version if plan else None
    validation_ids = {s.run_id for s in plan.validation_runs()} if plan else set()
    config_ids = {s.run_id for s in plan.runs()} if plan else set()
    planned_ids = config_ids | validation_ids
    passed = None
    issues_before = len(findings.lines)
    for i, event in enumerate(events, 1):
        kind = event["event"]
        if kind == "plan_decision":
            traced.append((event["plan_version"], event["decision"]))
            passed = None
        elif kind == "validation_finished":
            passed = event["passed"]
        elif kind == "run_started":
            rid = event["run_id"]
            where = f"trace.jsonl event {i} ({rid})"
            starts.add(rid)
            if not traced:
                findings.add("INSUFFICIENT", f"{where}: no prior plan decision in trace")
            elif traced[-1][1] != "approve" or (version and traced[-1][0] != version):
                findings.add("FAIL", f"{where}: latest decision does not approve this plan")
            if not event.get("plan_version") or not version:
                unversioned += 1
            elif event["plan_version"] != version or rid not in planned_ids:
                findings.add("FAIL", f"{where}: run does not match plan.json")
            if plan and plan.validation and rid in config_ids and passed is not True:
                findings.add("FAIL" if passed is False else "INSUFFICIENT", f"{where}: no prior passing validation")
    if unversioned:
        findings.add("INSUFFICIENT", f"trace.jsonl: {unversioned} run start(s) without a plan version, or no plan.json")
    if traced != decisions:
        findings.add("FAIL" if decisions and traced else "INSUFFICIENT",
                     "approvals.jsonl and trace.jsonl do not corroborate the same decisions")
    if len(findings.lines) == issues_before:
        findings.add("PASS", f"trace.jsonl and approvals.jsonl: {len(starts)} recorded starts checked")
    return starts


def _value(name: str, raw: Path, spec: SimulationRunSpec, custom: dict[str, str]) -> float:
    if name in custom:
        return recompute.custom_metrics(raw / "stdout.txt")[name]
    if name == "t90_ms":
        return recompute.t90_ms(raw / "stdout.txt", spec.params["NUM_OF_NODES"])
    func, filename = {
        "orphan_rate": (recompute.orphan_rate, "blockList.txt"),
        "stale_rate": (recompute.stale_rate, "SimOutput.csv"),
        "node0_block_share": (recompute.node0_block_share, "Chain.csv"),
    }[name]
    return func(raw / filename)


def _table(report: str, heading: str) -> list[list[str]]:
    """Read the first Markdown table in the named report section."""
    sections = report.split(f"\n## {heading}\n")
    if len(sections) != 2:
        raise ValueError(f"report.md: missing or ambiguous {heading} section")
    section = sections[1].split("\n## ", 1)[0]
    rows = [line.strip("|").split(" | ") for line in section.splitlines() if line.startswith("|")]
    if len(rows) < 2:
        raise ValueError(f"report.md: missing {heading} table")
    return [[cell.strip() for cell in row] for row in rows]


def _metrics(root: Path, plan: Plan, records: list[dict[str, Any]], starts: set[str], findings: Findings) -> None:
    expected = {s.run_id: s for s in plan.runs()}
    rows = {r["run_id"]: r for r in records}
    if len(rows) != len(records) or rows.keys() != expected.keys():
        findings.add("FAIL", "results.json: run IDs differ from plan.json")
        return
    report = (root / "report.md").read_text(encoding="utf-8")
    detail = _table(report, "Simulation runs")
    totals = _table(report, "Results")
    if (detail[0] != ["Run", "Status", *plan.metrics, "Raw output", "Changes"]
            or totals[0] != ["Configuration", *plan.metrics]):
        findings.add("INSUFFICIENT", "report.md: unrecognized metric table columns")
        return
    cells = {r[0]: r[2:-2] for r in detail[2:]}
    if len(cells) != len(detail[2:]) or cells.keys() != expected.keys():
        findings.add("FAIL", "report.md: simulation run rows differ from plan.json")
        return
    values: defaultdict[tuple[str, str], list[float]] = defaultdict(list)
    incomplete: set[tuple[str, str]] = set()
    count = 0
    before = len(findings.lines)
    for rid, spec in expected.items():
        row = rows[rid]
        if len(cells[rid]) != len(plan.metrics):
            findings.add("INSUFFICIENT", f"report.md: malformed row for {rid}")
            continue
        if row["status"] not in {"missing", "completed", "timeout", "failed"}:
            findings.add("FAIL", f"results.json: invalid status for {rid}")
        if set(row["metrics"]) - set(plan.metrics):
            findings.add("FAIL", f"results.json: unplanned metrics for {rid}")
        if row["status"] == "missing" and rid in starts:
            findings.add("FAIL", f"results.json: {rid} marked missing after recorded start")
        if row["status"] != "missing" and rid not in starts:
            findings.add("INSUFFICIENT", f"trace.jsonl: no start for {rid}")
        for idx, name in enumerate(plan.metrics):
            where = f"{rid}/{name}"
            if row["status"] != "completed" or (name in plan.custom_metrics and not spec.edited):
                if name in row["metrics"] or cells[rid][idx] != "-":
                    findings.add("FAIL", f"{where}: unexpected measurement in results.json or report.md")
                continue
            try:
                value = _value(name, root / "raw" / rid, spec, plan.custom_metrics)
                if not math.isfinite(value):
                    raise ValueError("non-finite measurement")
            except (OSError, ValueError, KeyError, ArithmeticError) as exc:
                findings.add("INSUFFICIENT", f"raw/{where}: {exc}")
                incomplete.add((spec.configuration, name))
                continue
            count += 1
            values[spec.configuration, name].append(value)
            saved = row["metrics"].get(name)
            if not isinstance(saved, (float, int)) or not math.isclose(value, saved, rel_tol=1e-12, abs_tol=1e-12):
                findings.add("FAIL", f"{where}: raw value {value} differs from results.json ({saved})")
            if cells[rid][idx] != format_value(value):
                findings.add("FAIL", f"{where}: report.md differs from raw value {value}")
    groups = {c["name"] for c in plan.data["configurations"]}
    if {r[0] for r in totals[2:]} != groups or len(totals[2:]) != len(groups):
        findings.add("FAIL", "report.md: Results configurations differ from plan.json")
    for row in totals[2:]:
        for name, cell in zip(plan.metrics, row[1:], strict=True):
            key = row[0], name
            if key in incomplete:
                continue
            vs = values[key]
            expected_cell = "no data"
            if vs:
                mean = format_value(statistics.fmean(vs))
                sd = f" ± {format_value(statistics.stdev(vs))}" if len(vs) > 1 else ""
                expected_cell = f"{mean}{sd} (n={len(vs)})"
            if cell != expected_cell:
                findings.add("FAIL", f"report.md Results: {row[0]}/{name}: expected {expected_cell}, found {cell}")
    if len(findings.lines) == before:
        findings.add("PASS", f"raw/, results.json and report.md: {count} measurements checked"
                     + (" (custom values checked against stdout only)" if plan.custom_metrics else ""))


def check_task(root: Path) -> tuple[int, list[str]]:
    findings = Findings()
    try:
        events = read_trace(root / "trace.jsonl")
        if not events or events[-1]["event"] != "task_finished":
            findings.add("INSUFFICIENT", "trace.jsonl: no final task_finished event")
        plan = load_plan(root / "plan.json") if (root / "plan.json").exists() else None
        starts = _order(root, plan, events, findings)
        records = json.loads((root / "results.json").read_text(encoding="utf-8"))
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("test_double"):
            findings.lines.append("NOTE: measurements come from a test double.")
        if plan:
            finished = {e["run_id"]: e["status"] for e in events if e["event"] == "run_finished"}
            for row in records:
                rid = row["run_id"]
                if rid in finished and finished[rid] != row["status"]:
                    findings.add("FAIL", f"{rid}: trace.jsonl and results.json disagree on run status")
                elif rid not in finished and row["status"] != "missing":
                    findings.add("INSUFFICIENT", f"trace.jsonl: no finish for {rid}")
            _metrics(root, plan, records, starts, findings)
        elif starts or records or not events or events[-1].get("status") not in {"rejected", "not_executed"}:
            findings.add("INSUFFICIENT", "plan.json: no executed plan to verify")
        else:
            findings.add("PASS", "results.json: no simulation measurements to verify")
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        findings.add("INSUFFICIENT", f"missing or unreadable task evidence: {exc}")
    code = 1 if "FAIL" in findings.status else 2 if "INSUFFICIENT" in findings.status else 0
    return code, findings.lines
