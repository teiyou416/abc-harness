"""Writes `report.md`: what was planned, what ran, and what was measured.

Every number in the report comes from `results.json`, and every row links to
the raw output it was computed from (AGENTS.md hard rule 6).
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from abc_harness.execution.task import RunRecord

from abc_harness.literature.library import Library
from abc_harness.planning.plan import Plan


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def _fmt(value: float) -> str:
    return f"{value:.4f}" if abs(value) < 1 else f"{value:.1f}"


def write_report(
    artifact_dir: Path,
    plan: Plan | None,
    records: list[RunRecord],
    manifest: dict[str, Any],
    summary: str | None = None,
) -> None:
    if plan is None:
        _write_planless_report(artifact_dir, manifest, summary)
        return
    lines = [
        f"# {plan.data['title']}",
        "",
        f"- Task: `{manifest['task_id']}`",
        f"- Status: **{manifest['status']}** ({manifest['stop_reason']})",
        f"- Plan version: `{plan.version}`",
        f"- Simulator: {plan.simulator} at `{manifest.get('simulator_revision', 'not prepared')}`",
        f"- Execution image: `{manifest.get('image_id', 'not used')}` (built as `{manifest.get('image', '-')}`)",
        (
            f"- Active runtime: {manifest['active_seconds']:.1f}s; "
            f"waiting for the researcher: {manifest['waiting_seconds']:.1f}s"
        ),
    ]
    if manifest.get("test_double"):
        lines.append("- **These results come from a test double, not from a real simulator.**")
    if manifest.get("cleanup_error"):
        lines.append(f"- **Container cleanup failed; check `docker ps` for leftovers:** {manifest['cleanup_error']}")
    if manifest.get("question"):
        lines.append(f"- Researcher's request: {manifest['question']}")
    lines += ["", f"Question: {plan.data['question']}", ""]
    if summary:
        lines += [
            "## Agent summary",
            "",
            "The agent wrote this summary. Every number in it must match the Results table below,",
            "which is computed from `results.json` and the raw output.",
            "",
            summary.strip(),
            "",
        ]

    lines += ["## Planned versus completed runs", "", "| Configuration | Planned | Completed | Not completed |", "|---|---|---|---|"]
    by_config: dict[str, list[RunRecord]] = {}
    for r in records:
        by_config.setdefault(r.configuration, []).append(r)
    for name, rs in by_config.items():
        missing = [f"{r.run_id} ({r.status})" for r in rs if r.status != "completed"]
        done = sum(r.status == "completed" for r in rs)
        lines.append(f"| {name} | {len(rs)} | {done} | {', '.join(missing) or '-'} |")

    lines += ["", "## Results", ""]
    lines += [
        "Each value is the mean over completed runs, with the sample standard deviation and the number of runs. "
        "Metric definitions are in `src/abc_harness/simulators/" + plan.simulator + ".py`.",
        "",
        "| Configuration | " + " | ".join(plan.metrics) + " |",
        "|---|" + "---|" * len(plan.metrics),
    ]
    for name, rs in by_config.items():
        done = [r for r in rs if r.status == "completed"]
        cells = []
        for metric in plan.metrics:
            values = [r.metrics[metric] for r in done]
            if not values:
                cells.append("no data")
            elif len(values) == 1:
                cells.append(f"{_fmt(values[0])} (n=1)")
            else:
                cells.append(f"{_fmt(statistics.fmean(values))} ± {_fmt(statistics.stdev(values))} (n={len(values)})")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")

    lines += _sources(artifact_dir, plan)
    lines += ["", "## Simulation runs", "", "| Run | Status | " + " | ".join(plan.metrics) + " | Raw output | Changes |"]
    lines.append("|---|---|" + "---|" * len(plan.metrics) + "---|---|")
    for r in records:
        metric_cells = [_fmt(r.metrics[m]) if m in r.metrics else "-" for m in plan.metrics]
        status = r.status if not r.error else f"{r.status}: {r.error}"
        raw = ", ".join(f"[{Path(f).name}]({f})" for f in r.raw_files) or "-"
        diff = f"[diff]({r.diff_file})" if r.diff_file else "-"
        lines.append(f"| {r.run_id} | {status} | " + " | ".join(metric_cells) + f" | {raw} | {diff} |")

    lines += [
        "",
        "## Reproduce",
        "",
        "Rerun the approved plan:",
        "",
        "```bash",
        f"uv run abc-harness run {manifest.get('plan_file') or artifact_dir / 'plan.json'}",
        "```",
        "",
        "Recalculate a run's metrics from its raw output without the harness:",
        "",
        "```bash",
        f"python3 scripts/recompute_metric.py {artifact_dir}/raw/<run_id> --nodes <NUM_OF_NODES>",
        "```",
        "",
    ]
    (artifact_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def _write_planless_report(artifact_dir: Path, manifest: dict[str, Any], summary: str | None) -> None:
    """Report for a task that never executed a plan: rejected, stopped, or ended by the agent."""
    lines = [
        "# Task without an executed plan",
        "",
        f"- Task: `{manifest['task_id']}`",
        f"- Status: **{manifest['status']}** ({manifest['stop_reason']})",
        f"- Plan versions proposed: {len(manifest.get('plan_versions', []))} (see `plans/` and `approvals.jsonl`)",
        "- No simulator was started.",
    ]
    if manifest.get("question"):
        lines.append(f"- Researcher's request: {manifest['question']}")
    if summary:
        lines += ["", "## Agent summary", "", summary.strip()]
    (artifact_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sources(artifact_dir: Path, plan: Plan) -> list[str]:
    """Each citation with the place the harness finds its quote, recomputed from the task's artifacts."""
    library = Library.load(artifact_dir)
    citations = plan.data.get("citations") or []
    if not citations and not library.searches:
        return []
    lines = ["", "## Sources", ""]
    for c in citations:
        paper = library.papers.get(c["paper"])
        if paper is None:
            lines.append(f"- **{c['supports']}**: `{c['paper']}`: \"{c['quote']}\" "
                         "(_not checked: this citation came with the plan file, not from a search in this task_)")  # fmt: skip
            continue
        where = library.locate(c["paper"], c["quote"])
        found = f"quote found in {where}" if where else "**quote not found in the saved text**"
        lines.append(f"- **{c['supports']}**: [{paper.title}]({paper.url}) ({paper.year}, {paper.venue or 'venue unknown'}): "
                     f"\"{c['quote']}\" ({found})")  # fmt: skip
    if not citations:
        lines.append("The plan cites no paper.")
    texts = "; full texts in `papers/`" if library.full_texts else ""
    lines += ["", f"{len(library.searches)} searches found {len(library.papers)} papers, all listed in `sources.json`{texts}."]
    return lines
