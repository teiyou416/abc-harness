"""Search the literature: first the configured venues, then everything when broadened."""

from __future__ import annotations

from typing import Any

from abc_harness.literature.library import MAX_RESULTS, VENUES
from abc_harness.tools.base import ToolContext, ToolError

SPEC: dict[str, Any] = {
    "name": "search_papers",
    "description": "Search academic papers by keywords. By default the search covers only the venues "
    f"{', '.join(VENUES)}; set broaden to true to search all venues and preprints when those give nothing "
    "relevant. Returns each paper's id, title, authors, year, venue, abstract, and whether read_paper can "
    "fetch its full text. Only papers returned here can be cited in a plan.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Keywords, for example 'bitcoin block propagation delay'."},
            "broaden": {"type": "boolean", "description": "Search beyond the first-round venues. Default false."},
            "limit": {"type": "integer", "description": f"Number of results, 1 to {MAX_RESULTS}. Default 5."},
        },
        "required": ["query"],
    },
}


def run(ctx: ToolContext, args: dict[str, Any]) -> str:
    if ctx.library is None:
        raise ToolError("literature search is not configured for this task")
    query = str(args.get("query", "")).strip()
    if not query:
        raise ToolError("query must not be empty")
    broaden = bool(args.get("broaden", False))
    try:
        limit = int(args.get("limit") or 5)
    except (TypeError, ValueError) as e:
        raise ToolError("limit must be a whole number") from e
    ctx.task.budget.check_time()
    papers, errors = ctx.library.search(query, broaden, limit, ctx.task.budget.remaining_seconds)
    if not papers and errors:
        raise ToolError("the search failed: " + "; ".join(errors))
    scope = "all venues and preprints" if broaden else f"venues {', '.join(VENUES)}"
    header = f"[{len(papers)} results for {query!r} in {scope}]"
    if errors:
        header += " [partial: " + "; ".join(errors) + "]"
    if not papers:
        return header + "\nNothing found." + ("" if broaden else " Try other keywords or broaden: true.")
    return header + "\n\n" + "\n\n".join(p.brief() for p in papers)
