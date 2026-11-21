"""Fetch a paper's full text (arXiv HTML, or a PDF parsed by MinerU) and save it for paging with read_file."""

from __future__ import annotations

from typing import Any

from abc_harness.literature.fulltext import outline
from abc_harness.literature.http import FetchError
from abc_harness.literature.pdf import PdfError
from abc_harness.tools.base import ToolContext, ToolError

FIRST_LINES = 15

SPEC: dict[str, Any] = {
    "name": "read_paper",
    "description": "Open the full text of a paper found by search_papers (if it has an arXiv version) or "
    "listed from the researcher's local library (a PDF, parsed on first read). arXiv papers come from arXiv's HTML, or from the arXiv PDF parsed by "
    "MinerU when there is no HTML; that can take a few minutes, which do not count toward the task's time limit. "
    "The harness saves the text as task/papers/<id>.txt and returns where it came from, the section outline "
    "with line numbers, and the figures (and, for PDFs, tables) you can view; read sections with read_file "
    "using offset and limit. Quotes from this text can support citations.",
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
    if not paper.arxiv_id and paper_id not in ctx.library.full_texts and paper_id not in ctx.library.shelf:
        raise ToolError(f"{paper_id} has no arXiv version, so its full text is not available; use its abstract")
    ctx.task.budget.check_time()
    try:
        rel, lines = ctx.library.read(paper_id, ctx.task.budget.remaining_seconds)
    except FetchError as e:
        raise ToolError(f"could not fetch the full text: {e}") from e
    except PdfError as e:
        if paper_id in ctx.library.shelf:
            raise ToolError(f"the PDF could not be parsed: {e}") from e
        raise ToolError(f"arXiv has no HTML for this paper and its PDF could not be parsed: {e}") from e
    sections = "\n".join(outline(lines)) or "(no section headings found)"
    figures = "\n".join(f"- {f.label} (at line {f.line}): {f.caption[:160]}"
                        for f in ctx.library.figures.get(paper_id, [])) or "(no figures with images)"  # fmt: skip
    from_pdf = ctx.library.sources.get(paper_id, {}).get("kind") == "pdf"
    listed = ("Figures and tables (view one with view_figure; view a table before using its numbers)" if from_pdf
              else "Figures (view one with view_figure; tables are text in the outline)")  # fmt: skip
    header = "\n".join(line for line in lines[:2] if line.startswith(("# Source:", "# Note:")))
    first = "\n".join(lines[:FIRST_LINES])
    return (f"[{paper.title}: saved to task/{rel}, {len(lines)} lines. Read sections with read_file.]\n"
            f"{header}\n\nOutline:\n{sections}\n\n{listed}:\n{figures}\n\nFirst {FIRST_LINES} lines:\n{first}")  # fmt: skip
