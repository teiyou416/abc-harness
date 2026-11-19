"""Validate a plan, show it to the researcher, and return their decision."""

from __future__ import annotations

import json
from typing import Any

from abc_harness.execution.runner import RunnerError
from abc_harness.execution.task import FAILED, REJECTED
from abc_harness.literature.library import MIN_QUOTE_CHARS
from abc_harness.planning.plan import PlanError, validate_plan
from abc_harness.simulators import SIMULATORS, SimulatorError
from abc_harness.tools.base import EndTask, ToolContext, ToolError

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "Short name of the experiment."},
        "question": {"type": "string", "description": "The research question this plan answers."},
        "simulator": {"type": "string", "enum": sorted(SIMULATORS)},
        "rationale": {
            "type": "string",
            "description": "Why this simulator fits, citing capability card entry IDs, plus assumptions and limits.",
        },
        "seeds": {"type": "array", "items": {"type": "integer"}, "description": "Distinct integer seeds."},
        "metrics": {"type": "array", "items": {"type": "string"}, "description": "Built-in metrics from the "
                    "capability card, and any custom_metrics you define."},
        "custom_metrics": {
            "type": "array",
            "description": "Only with permitted_edits, when the question needs a quantity no built-in metric "
            "measures (for example the attacker's revenue share). Each has a new name and a precise definition; "
            "your edited source prints one line 'ABC_METRIC <name>=<value>' to stdout at the end of each run, and "
            "the harness reads it. Never give a built-in metric a new meaning instead.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Lowercase letters, digits, _; e.g. attacker_revenue_share."},
                    "definition": {"type": "string", "description": "What is counted and divided by what, e.g. "
                                   "'blocks mined by the pool on the final main chain / all main-chain blocks'."},
                },
                "required": ["name", "definition"],
            },
        },
        "run_timeout_seconds": {"type": "integer", "description": "Timeout for one simulation run."},
        "baseline": {"type": "object", "description": "Parameters shared by every configuration."},
        "permitted_edits": {
            "type": "array",
            "description": "Only when the simulator lacks a capability the question needs: the source files you "
            "will create or change after approval, each with its purpose. Paths are relative to the source root "
            "(the card's 'Where the code is' section). Needs a validation check.",
            "items": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "purpose": {"type": "string"}},
                "required": ["path", "purpose"],
            },
        },
        "validation": {
            "type": "object",
            "description": "Required with permitted_edits. A deterministic check the harness runs on your edited "
            "source before any configuration: the mean of one plan metric over the given seeds must equal "
            "expected within tolerance, for a case with a known answer (e.g. a closed-form result from a paper). "
            "If it fails, the task stops.",
            "properties": {
                "description": {"type": "string", "description": "What the check shows and where expected comes from."},
                "params": {"type": "object", "description": "Parameters that differ from the baseline for the check."},
                "seeds": {"type": "array", "items": {"type": "integer"}},
                "metric": {"type": "string"},
                "expected": {"type": "number"},
                "tolerance": {"type": "number"},
            },
            "required": ["description", "params", "seeds", "metric", "expected", "tolerance"],
        },
        "citations": {
            "type": "array",
            "description": "Papers from search_papers that justify a choice in this plan. Leave out when none does.",
            "items": {
                "type": "object",
                "properties": {
                    "paper": {"type": "string", "description": "The paper id returned by search_papers."},
                    "supports": {
                        "type": "string",
                        "description": "The parameter, assumption, or metric it justifies, e.g. 'Bdelay = 12.6'.",
                    },
                    "quote": {
                        "type": "string",
                        "description": "A sentence copied verbatim from the abstract or the saved full text. "
                        "Give either quote, or figure and reading.",
                    },
                    "figure": {"type": "string", "description": "A figure you viewed, e.g. 'Figure 3'."},
                    "reading": {
                        "type": "string",
                        "description": "The value read off the figure with its uncertainty and where on the axes, "
                        "e.g. '0.954 ± 0.003 at horizon 10 (log x axis), curve alpha = 0.45'.",
                    },
                },
                "required": ["paper", "supports"],
            },
        },
        "configurations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Letters, digits, - and _ only."},
                    "params": {"type": "object", "description": "Parameters that differ from the baseline."},
                    "edits": {
                        "type": "boolean",
                        "description": "Only with permitted_edits: run the edited source (default true) or the "
                        "original source (false), e.g. for an honest-mining comparison.",
                    },
                },
                "required": ["name"],
            },
        },
    },
    "required": [
        "title", "question", "simulator", "rationale", "seeds", "metrics",
        "run_timeout_seconds", "baseline", "configurations",
    ],
}  # fmt: skip

SPEC: dict[str, Any] = {
    "name": "propose_plan",
    "description": "Submit a complete experiment plan. The harness validates it, shows it to the researcher, "
    "and returns their decision (approve, revise with a comment, or reject) and the plan_version.",
    "input_schema": PLAN_SCHEMA,
}


def run(ctx: ToolContext, args: dict[str, Any]) -> str:
    if ctx.execution:
        raise ToolError("this task already ran a plan; write your final answer instead")
    if "execution_image" in args:
        raise ToolError("plan refused: leave out execution_image; the harness pins the image itself")
    try:
        plan = validate_plan(dict(args))
    except (PlanError, SimulatorError) as e:
        raise ToolError(f"plan refused: {e}") from e
    problems = check_citations(ctx, plan.data.get("citations", []))
    if problems:
        raise ToolError("plan refused: " + "; ".join(problems))
    try:
        plan = ctx.task.pin_image(plan)
    except RunnerError as e:
        raise EndTask(FAILED, str(e)) from e
    ctx.task.add_plan(plan)
    decision, comment = ctx.task.review(plan, ctx.review)
    if decision == "reject":
        raise EndTask(REJECTED, "plan rejected by researcher" + (f": {comment}" if comment else ""))
    return json.dumps({"plan_version": plan.version, "decision": decision, "comment": comment})


def check_citations(ctx: ToolContext, citations: list[dict[str, str]]) -> list[str]:
    """Every cited paper must come from this task's searches; a quote must appear in it verbatim, and a
    figure reading must come from a figure viewed in this task."""
    problems = []
    for c in citations:
        if ctx.library is None or c["paper"] not in ctx.library.papers:
            problems.append(f"{c['paper']} was not returned by search_papers or supplied by the researcher in this task")
        elif "figure" in c:
            if ctx.library.figure(c["paper"], c["figure"]) is None:
                problems.append(f"{c['paper']} has no {c['figure']!r} in its saved full text")
            elif not any(label.lower() == c["figure"].strip().lower()
                         for label in ctx.library.viewed.get(c["paper"], {})):  # fmt: skip
                problems.append(f"{c['figure']} of {c['paper']} was not viewed with view_figure in this task")
        elif ctx.library.in_pdf_table(c["paper"], c["quote"]):
            problems.append(f"the quote for {c['paper']} comes from a table recognized from the PDF, whose numbers "
                            "may be wrong; view the table with view_figure and cite the value as a figure reading")  # fmt: skip
        elif ctx.library.locate(c["paper"], c["quote"]) is None:
            where = "its abstract or saved full text" if c["paper"] in ctx.library.full_texts else "its abstract"
            problems.append(f"the quote for {c['paper']} does not appear verbatim in {where} "
                            f"(at least {MIN_QUOTE_CHARS} characters; read_paper first to quote the full text)")  # fmt: skip
    return problems
