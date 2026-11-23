"""Keep a paper the agent has read in the researcher's local library, when the paper is worth keeping.

Reading a paper (read_paper) saves its text only in the task. This tool copies the paper's PDF into the local
library, optionally in a folder, after checking the library's index for the same file, arXiv id, DOI, or title.
The harness does the writing; the agent never writes to the library itself (AGENTS.md hard rule 4).
"""

from __future__ import annotations

from typing import Any

from abc_harness.literature.library import KeepError
from abc_harness.tools.base import ToolContext, ToolError

SPEC: dict[str, Any] = {
    "name": "save_paper",
    "description": "Keep a paper you have read with read_paper in the researcher's local library, as its PDF named "
    "by the paper's title, so later tasks can read it without searching. Keep a paper only when the researcher "
    "asks for it, or when it supports a plan the researcher approved; reading a paper does not keep it. The "
    "harness checks the library first and does not save a paper it already holds (the same file, arXiv id, DOI, "
    "or title); it then says where the existing copy is.",
    "input_schema": {
        "type": "object",
        "properties": {
            "paper": {"type": "string", "description": "The paper id, as read with read_paper."},
            "folder": {
                "type": "string",
                "description": "Optional folder inside the library, such as security; at most three levels. "
                "Omit to save at the top of the library.",
            },
        },
        "required": ["paper"],
    },
}


def run(ctx: ToolContext, args: dict[str, Any]) -> str:
    library = ctx.library
    if library is None or library.library_dir is None:
        raise ToolError("this task has no local library")
    ctx.task.budget.check_time()
    try:
        path, duplicate = library.keep(str(args.get("paper", "")), str(args.get("folder") or ""),
                                       ctx.task.budget.remaining_seconds)  # fmt: skip
    except KeepError as e:
        raise ToolError(str(e)) from e
    where = f"{library.library_dir.name}/{path}"
    if duplicate:
        return f"Not saved: {duplicate}, as {where}."
    return f"Saved in the researcher's local library as {where}; the library index records it."
