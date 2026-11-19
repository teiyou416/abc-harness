"""Show the model one figure of a paper it has read, and record that it was viewed."""

from __future__ import annotations

from typing import Any

from abc_harness.literature.http import FetchError
from abc_harness.tools.base import ToolContext, ToolError, ToolOutput

SPEC: dict[str, Any] = {
    "name": "view_figure",
    "description": "Show one figure of a paper you opened with read_paper, as an image with its caption. The "
    "outline from read_paper lists the figures. Only a figure you viewed can support a figure reading in a "
    "plan. Tables are text in the saved full text; read them with read_file instead.",
    "input_schema": {
        "type": "object",
        "properties": {
            "paper": {"type": "string", "description": "The paper id from search_papers."},
            "figure": {"type": "string", "description": "The figure label from the outline, e.g. 'Figure 3'."},
        },
        "required": ["paper", "figure"],
    },
}


def run(ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
    if ctx.library is None:
        raise ToolError("literature search is not configured for this task")
    paper_id, label = str(args.get("paper", "")), str(args.get("figure", ""))
    if paper_id not in ctx.library.full_texts:
        raise ToolError(f"call read_paper for {paper_id!r} first; it lists the paper's figures")
    figure = ctx.library.figure(paper_id, label)
    if figure is None:
        listed = ", ".join(f.label for f in ctx.library.figures.get(paper_id, [])) or "none"
        raise ToolError(f"{paper_id} has no {label!r}; its figures are: {listed}")
    ctx.task.budget.check_time()
    try:
        figure, images, skipped = ctx.library.view(paper_id, figure.label, ctx.task.budget.remaining_seconds)
    except FetchError as e:
        raise ToolError(f"could not fetch the figure: {e}") from e
    if not images:
        raise ToolError(f"{figure.label} cannot be shown: " + "; ".join(skipped) + ". Use its caption instead.")
    text = [f"[{paper_id} {figure.label}, {len(images)} image(s), saved as "
            + ", ".join(f"task/{rel}" for rel, _ in images) + "]",
            f"Caption (task/{ctx.library.full_texts[paper_id]} line {figure.line}): {figure.caption}"]  # fmt: skip
    if skipped:
        text.append("Not shown: " + "; ".join(skipped))
    return ToolOutput("\n".join(text), images)
