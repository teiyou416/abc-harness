"""The agent's tools, one module per tool (docs/context/conventions.md §3).

Each module exports `SPEC`, the definition sent to the model, and
`run(ctx, args)`, the harness code that executes it. This list is the whole
set of things the agent can do; nothing is discovered automatically.
"""

from __future__ import annotations

from typing import Any

from abc_harness.tools import (
    ask_researcher,
    describe_simulator,
    edit_file,
    make_figure,
    propose_plan,
    read_file,
    read_paper,
    run_command,
    run_plan,
    save_paper,
    search_files,
    search_papers,
    view_figure,
    write_file,
)
from abc_harness.tools.base import EndTask, ToolContext, ToolError, ToolOutput, ToolRun

_MODULES = (
    describe_simulator, read_file, search_files, search_papers, read_paper, save_paper, view_figure, ask_researcher, propose_plan,
    write_file, edit_file, run_command, run_plan, make_figure,
)  # fmt: skip

TOOLS: list[dict[str, Any]] = [m.SPEC for m in _MODULES]
HANDLERS: dict[str, ToolRun] = {m.SPEC["name"]: m.run for m in _MODULES}

__all__ = ["HANDLERS", "TOOLS", "EndTask", "ToolContext", "ToolError", "ToolOutput"]
