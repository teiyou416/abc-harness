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
    propose_plan,
    read_file,
    read_paper,
    run_plan,
    search_papers,
)
from abc_harness.tools.base import EndTask, ToolContext, ToolError, ToolRun

_MODULES = (describe_simulator, read_file, search_papers, read_paper, ask_researcher, propose_plan, run_plan)

TOOLS: list[dict[str, Any]] = [m.SPEC for m in _MODULES]
HANDLERS: dict[str, ToolRun] = {m.SPEC["name"]: m.run for m in _MODULES}

__all__ = ["HANDLERS", "TOOLS", "EndTask", "ToolContext", "ToolError"]
