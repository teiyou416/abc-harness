"""Draw a figure of this task's results with a matplotlib script run in the plot image."""

from __future__ import annotations

from typing import Any

from abc_harness.execution.figures import PLOT_TIMEOUT_SECONDS, FigureError, draw
from abc_harness.tools.base import ToolContext, ToolError, ToolOutput

MAX_SCRIPT_CHARS = 20_000
MAX_CAPTION_CHARS = 800

SPEC: dict[str, Any] = {
    "name": "make_figure",
    "description": "Draw a static figure of this task's results, after run_plan. Write a Python script; the "
    "harness runs it in a container with matplotlib, numpy, and the `abcplot` helper, with no network, the "
    "results read-only under /data (results.json, plan.json, validation.json, raw/), and only /out writable. "
    "Read every value with abcplot (summary, runs, params, plan) or from /data; never type a number into the "
    "script. Start with abcplot.use_style(), draw at its final size with abcplot.figure(), and end with "
    "abcplot.save(fig), which writes /out/figure.svg and /out/figure.png. The result shows you the PNG; "
    "check it and call again with the same name to replace it. The report shows each figure with its "
    f"caption and script. A script may run for {PLOT_TIMEOUT_SECONDS}s.",
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "File name: lowercase letters, digits, hyphens, e.g. "
                     "'revenue-vs-alpha'. The same name replaces an earlier figure."},
            "script": {"type": "string", "description": "The complete Python script."},
            "caption": {"type": "string", "description": "What the figure shows, including what the error bars "
                        "are and how many seeds each point averages, e.g. 'Stale rate per configuration; mean "
                        "± sample standard deviation over 5 seeds.'"},
        },
        "required": ["name", "script", "caption"],
    },
}


def run(ctx: ToolContext, args: dict[str, Any]) -> ToolOutput:
    name = str(args.get("name", "")).strip()
    script = str(args.get("script", ""))
    caption = " ".join(str(args.get("caption", "")).split())
    if ctx.task.executed is None:
        raise ToolError("there are no results to draw yet; figures plot this task's results after run_plan")
    if not script.strip() or len(script) > MAX_SCRIPT_CHARS:
        raise ToolError(f"script must be 1 to {MAX_SCRIPT_CHARS} characters")
    if not caption or len(caption) > MAX_CAPTION_CHARS:
        raise ToolError(f"caption must be 1 to {MAX_CAPTION_CHARS} characters")
    ctx.task.budget.check_time()
    try:
        drawn = draw(ctx.task, name, script, caption)
    except FigureError as e:
        raise ToolError(f"figure {name!r} was not drawn: {e}") from e
    files = f"task/{drawn.png}" + (f" and task/{drawn.svg}" if drawn.svg else "")
    text = [f"[figure {name}: saved {files}; script task/{drawn.script}]", f"Caption: {caption}"]
    if drawn.output.strip():
        text.append(f"Script output:\n{drawn.output.strip()}")
    if not ctx.sees_images:
        text.append("The model running this task cannot see images, so the figure is saved and in the report but "
                    "not shown to you. Check the script instead: every value read from the results, axis labels with "
                    "units, error bars.")  # fmt: skip
        return ToolOutput("\n".join(text))
    text.append("Check the image: axis labels with units, error bars, readable legend. "
                "Call make_figure again with the same name to fix it.")  # fmt: skip
    return ToolOutput("\n".join(text), [(drawn.png, drawn.png_bytes)])
