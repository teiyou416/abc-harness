"""Sandbox exec: run a command inside the execution image to build and test the agent's code.

The edited source is mounted read-only at /work/src and scratch/ is the writable working directory
/work/scratch, so a command cannot change a source file. There is no network and no host environment.
The output never counts as a result: only run_plan's simulation runs reach the report.
"""

from __future__ import annotations

from typing import Any

from abc_harness.execution.runner import SANDBOX_SCRATCH, SANDBOX_SOURCE
from abc_harness.tools.base import ToolContext, ToolError
from abc_harness.tools.edits import approved_plan_with_edits

DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 600
OUTPUT_CHARS = 9000  # the model sees the end of the output; the log keeps all of it

SPEC: dict[str, Any] = {
    "name": "run_command",
    "description": f"Run a shell command in the simulator's execution image to build or test your code. Each "
    f"command runs in a new container and starts in {SANDBOX_SCRATCH}, so no `cd` is needed. What lasts between "
    f"commands: files in {SANDBOX_SCRATCH} (scratch/), such as compiled classes and test scripts. What does not: "
    "the current directory, environment variables, background processes, and files anywhere else. The container "
    f"holds only {SANDBOX_SOURCE} (your edited source, read-only) and {SANDBOX_SCRATCH} (writable); the plan, "
    "papers, and results are not in it, so read them with read_file or search_files. The image has the "
    "simulator's own toolchain (SimBlock: JDK 21 and a POSIX shell, no Python; BlockSim: Python 3.11 with pandas) and no network, so "
    "nothing can be installed. Long output is cut to its last part; the whole of it is in the log the result "
    "names. Only after approval of a plan with permitted edits. The output is for your own checks; it never "
    "counts as a result.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout_seconds": {"type": "integer", "description": f"Default {DEFAULT_TIMEOUT}, at most {MAX_TIMEOUT}."},
        },
        "required": ["command"],
    },
}


def run(ctx: ToolContext, args: dict[str, Any]) -> str:
    plan = approved_plan_with_edits(ctx)
    command = str(args.get("command", "")).strip()
    if not command:
        raise ToolError("command must not be empty")
    try:
        timeout = min(MAX_TIMEOUT, max(1, int(args.get("timeout_seconds") or DEFAULT_TIMEOUT)))
    except (TypeError, ValueError) as e:
        raise ToolError("timeout_seconds must be a whole number") from e
    ctx.task.budget.check_time()
    outcome, log = ctx.task.sandbox(plan, command, timeout)
    status = "timed out" if outcome.timed_out else f"exit code {outcome.exit_code}"
    output = outcome.output or "(no output)"
    if len(output) > OUTPUT_CHARS:
        # Keep the end, where errors and test summaries usually are.
        output = f"[showing the last {OUTPUT_CHARS} of {len(output)} characters]\n" + output[-OUTPUT_CHARS:]
    return f"[{status} after {outcome.duration_seconds:.1f}s; full output in task/{log}]\n{output}"
