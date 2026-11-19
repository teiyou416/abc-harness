"""Fetch a paper's full text from arXiv and save it in the task for paging with read_file."""

from __future__ import annotations

from typing import Any

from abc_harness.literature.fulltext import outline
from abc_harness.literature.http import FetchError
from abc_harness.tools.base import ToolContext, ToolError

FIRST_LINES = 15

SPEC: dict[str, Any] = {
    "name": "read_paper",
    "description": "Fetch the full text of a paper found by search_papers, if it has an arXiv version. The "
    "harness saves it as task/papers/<arxiv_id>.txt and returns the section outline with line numbers; read "
    "sections with read_file using offset and limit. Quotes from this text can support citations.",
    "input_schema": {
        "type": "object",
        "properties": {"paper": {"type": "string", "description": "The paper id from search_papers."}},
        "required": ["paper"],
    },
}


def run(ctx: ToolContext, args: dict[str, Any]) -> str:
    if ctx.library is None:
        raise ToolError("literature search is not configured for this task")
    paper_id = str(args.get("paper", ""))
    paper = ctx.library.papers.get(paper_id)
    if paper is None:
        raise ToolError(f"unknown paper {paper_id!r}; use an id returned by search_papers")
    if not paper.arxiv_id:
        raise ToolError(f"{paper_id} has no arXiv version, so its full text is not available; use its abstract")
    ctx.task.budget.check_time()
    try:
        rel, lines = ctx.library.read(paper_id, ctx.task.budget.remaining_seconds)
    except FetchError as e:
        raise ToolError(f"could not fetch the full text: {e}") from e
    sections = "\n".join(outline(lines)) or "(no section headings found)"
    first = "\n".join(lines[:FIRST_LINES])
    return (f"[{paper.title}: saved to task/{rel}, {len(lines)} lines. Read sections with read_file.]\n\n"
            f"Outline:\n{sections}\n\nFirst {FIRST_LINES} lines:\n{first}")  # fmt: skip
