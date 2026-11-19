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
    lines += _pdf_parse_line(manifest)
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
    for name, cells in metric_rows(records, plan.metrics):
        lines.append(f"| {name} | " + " | ".join(cells) + " |")

    lines += _code_changes(artifact_dir, plan, manifest)
    lines += _citations(artifact_dir, plan)
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


def metric_rows(records: list[RunRecord], metrics: list[str]) -> list[tuple[str, list[str]]]:
    """Per configuration, each metric as "mean ± sd (n=k)" over completed runs, or "no data"."""
    by_config: dict[str, list[RunRecord]] = {}
    for r in records:
        by_config.setdefault(r.configuration, []).append(r)
    rows = []
    for name, rs in by_config.items():
        done = [r for r in rs if r.status == "completed"]
        cells = []
        for metric in metrics:
            values = [r.metrics[metric] for r in done if metric in r.metrics]
            if not values:
                cells.append("no data")
            elif len(values) == 1:
                cells.append(f"{_fmt(values[0])} (n=1)")
            else:
                cells.append(f"{_fmt(statistics.fmean(values))} ± {_fmt(statistics.stdev(values))} (n={len(values)})")
        rows.append((name, cells))
    return rows


def _write_planless_report(artifact_dir: Path, manifest: dict[str, Any], summary: str | None) -> None:
    """Report for a task that never executed a plan: rejected, stopped, or ended by the agent."""
    lines = [
        "# Task without an executed plan",
        "",
        f"- Task: `{manifest['task_id']}`",
        f"- Status: **{manifest['status']}** ({manifest['stop_reason']})",
        f"- Plan versions proposed: {len(manifest.get('plan_versions', []))} (see `plans/` and `approvals.jsonl`)",
        "- No simulation run was started.",
    ]
    lines += _pdf_parse_line(manifest)
    if (artifact_dir / "sandbox").exists():
        lines.append("- The agent ran sandbox commands (`sandbox/`) and edited source (`workspace/edited/`); "
                     "they are not results.")  # fmt: skip
    if manifest.get("question"):
        lines.append(f"- Researcher's request: {manifest['question']}")
    if summary:
        lines += ["", "## Agent summary", "", summary.strip()]
    (artifact_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _citations(artifact_dir: Path, plan: Plan) -> list[str]:
    """Each citation with what the harness found for it, recomputed from the task's artifacts."""
    library = Library.load(artifact_dir)
    citations = plan.data.get("citations") or []
    if not citations and not library.searches:
        return []
    lines = ["", "## Citations", ""]
    for c in citations:
        evidence = f"\"{c['quote']}\"" if "quote" in c else f"{c['figure']}: {c['reading']}"
        paper = library.papers.get(c["paper"])
        if paper is None:
            lines.append(f"- **{c['supports']}**: `{c['paper']}`: {evidence} "
                         "(_not checked: this citation came with the plan file, not from a search in this task_)")  # fmt: skip
            continue
        if "quote" in c:
            where = library.locate(c["paper"], c["quote"])
            found = f"quote found in {where}" if where else "**quote not found in the saved text**"
        else:
            saved = next((v for k, v in library.viewed.get(c["paper"], {}).items()
                          if k.lower() == c["figure"].strip().lower()), None)  # fmt: skip
            images = ", ".join(f"[image]({rel})" for rel in saved) if saved else "**figure not viewed**"
            found = f"_figure reading: read off the figure by the model, approximate, not checked against text_; {images}"
        lines.append(f"- **{c['supports']}**: [{paper.title}]({paper.url}) ({paper.year or 'n.d.'}, "
                     f"{paper.venue or 'venue unknown'}): {evidence} ({found}{_text_source(library, c['paper'])})")  # fmt: skip
    if not citations:
        lines.append("The plan cites no paper.")
    texts = "; full texts and viewed figures in `papers/`" if library.full_texts else ""
    lines += ["", f"{len(library.searches)} searches found {len(library.papers)} papers, all listed in `literature.json`{texts}."]
    return lines


def _pdf_parse_line(manifest: dict[str, Any]) -> list[str]:
    parses = manifest.get("pdf_parses") or []
    if not parses:
        return []
    cached = sum(1 for p in parses if p.get("cached"))
    reused = f", {cached} reused from the parse cache" if cached else ""
    return [(f"- PDF parsing: {len(parses)} PDF(s){reused}; {manifest.get('pdf_parse_seconds', 0):.1f}s, "
            "not counted in active runtime")]  # fmt: skip


def _text_source(library: Library, paper_id: str) -> str:
    source = library.sources.get(paper_id, {})
    if source.get("kind") != "pdf":
        return ""
    return f"; full text machine-recognized from [the PDF]({source['pdf']}) by MinerU, so it may differ from the paper"


def _code_changes(artifact_dir: Path, plan: Plan, manifest: dict[str, Any]) -> list[str]:
    """The agent's edits, the validation check that gated the experiment, and the sandbox commands it ran."""
    if not plan.permitted_paths:
        return []
    lines = ["", "## Code changes and validation", ""]
    edited = manifest.get("edited_files")
    if edited is None:
        lines.append("The plan was not executed, so the edited source was never frozen.")
    elif edited:
        lines.append(f"The agent changed {', '.join(f'`{f}`' for f in edited)}. Full diff against the pinned "
                     "revision: [changes/edits.diff](changes/edits.diff). Export the source with "
                     f"`uv run abc-harness export {artifact_dir}`.")  # fmt: skip
    else:
        lines.append("The plan permitted edits, but the agent changed no file.")
    check = plan.validation or {}
    result_path = artifact_dir / "validation.json"
    lines += ["", f"Validation check: {check.get('description', '')}"]
    if result_path.exists():
        result = json.loads(result_path.read_text(encoding="utf-8"))
        mean = "no data" if result["mean"] is None else _fmt(result["mean"])
        verdict = "**passed**" if result["passed"] else "**failed; no configuration was run**"
        lines += ["", (f"Mean {result['metric']} over {result['n']} of {result['planned']} validation runs: {mean}; "
                       f"required {result['expected']} ± {result['tolerance']}: {verdict}. "
                       "Runs and raw output: [validation.json](validation.json).")]  # fmt: skip
    elif edited is not None:
        lines += ["", "The validation check did not finish."]
    logs = sorted((artifact_dir / "sandbox").glob("*.log")) if (artifact_dir / "sandbox").exists() else []
    if logs:
        lines += ["", (f"The agent ran {len(logs)} sandbox commands to build and test its code "
                       "([sandbox/](sandbox/)); their output is not a result. Its test files are in "
                       "[workspace/scratch/](workspace/scratch/).")]  # fmt: skip
    return lines
