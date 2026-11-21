"""Figures the agent draws from this task's results (the make_figure tool).

The agent writes a matplotlib script; the harness runs it in the plot image
with the task's results read-only at /data and only an output folder
writable, so the script can neither read anything else nor reach the network.
The script, its PNG and SVG, and its output are kept side by side in
`figures/`, and `figures/index.json` lists each figure with its caption, so
the report can show every figure next to the code that drew it.

A script can still type a number instead of reading it, which the harness
cannot prevent; keeping the script beside the figure makes that visible.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from abc_harness.execution.limits import LimitReached
from abc_harness.execution.runner import RunnerError
from abc_harness.literature.figures import image_size, media_type

if TYPE_CHECKING:
    from abc_harness.execution.task import Task

PLOT_IMAGE = "abc-harness-plot:mpl-3.11.2"
PLOT_TIMEOUT_SECONDS = 120
FIGURES_DIR = "figures"
INDEX_FILE = "figures/index.json"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")
MAX_PNG_BYTES = 5_000_000
MAX_PNG_EDGE = 4000
DATA_FILES = ("results.json", "plan.json", "validation.json", "raw")


class FigureError(Exception):
    """The figure could not be drawn; the message, with the script's output, goes back to the agent."""


@dataclass
class DrawnFigure:
    name: str
    png: str  # paths relative to the artifact directory
    svg: str | None
    script: str
    png_bytes: bytes
    output: str


def load_index(artifact_dir: Path) -> dict[str, dict[str, Any]]:
    path = artifact_dir / INDEX_FILE
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def draw(task: Task, name: str, script: str, caption: str) -> DrawnFigure:
    """Run one figure script in the plot image and keep its output. Raises FigureError or LimitReached."""
    if not NAME.match(name):
        raise FigureError("name must be 1 to 48 lowercase letters, digits, or hyphens, e.g. 'revenue-vs-alpha'")
    try:
        image_id = task.runner.image_info(PLOT_IMAGE)["image_id"]
    except RunnerError as e:
        raise FigureError(f"the plot image {PLOT_IMAGE} is missing; run `abc-harness image build`") from e
    task.write_results()
    root = task.artifact_dir
    folder = root / FIGURES_DIR
    folder.mkdir(exist_ok=True)
    script_path = folder / f"{name}.py"
    script_path.write_text(script, encoding="utf-8")
    staging = folder / f".out-{name}"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    data = [root / f for f in DATA_FILES if (root / f).exists()]

    task.figure_calls += 1
    timeout = min(PLOT_TIMEOUT_SECONDS, task.budget.remaining_seconds)
    task.started_containers = True
    task.trace.event("figure_started", name=name, call=task.figure_calls, timeout_seconds=timeout)
    outcome = task.runner.plot(image_id, task.task_id, f"figure-{task.figure_calls}", data, script_path, staging,
                               timeout)  # fmt: skip
    output = outcome.output[-4000:]
    (folder / f"{name}.log").write_text(outcome.output, encoding="utf-8")
    try:
        if outcome.timed_out:
            if timeout < PLOT_TIMEOUT_SECONDS:
                raise LimitReached("time", f"active runtime ran out while drawing figure {name}")
            raise FigureError(f"the script did not finish within {PLOT_TIMEOUT_SECONDS}s")
        if outcome.exit_code != 0:
            raise FigureError(f"the script failed with exit code {outcome.exit_code}:\n{output}")
        png = (staging / "figure.png").read_bytes() if (staging / "figure.png").is_file() else b""
        if media_type(png) != "image/png":
            raise FigureError("the script wrote no /out/figure.png; end it with abcplot.save(fig)")
        size = image_size(png) or (0, 0)
        if len(png) > MAX_PNG_BYTES or max(size) > MAX_PNG_EDGE:
            raise FigureError(f"figure.png is too large ({size[0]}x{size[1]} px, {len(png)} bytes); "
                              f"keep it under {MAX_PNG_EDGE} px a side")  # fmt: skip
    except FigureError as e:
        task.trace.event("figure_finished", name=name, ok=False, exit_code=outcome.exit_code,
                         timed_out=outcome.timed_out, duration_seconds=round(outcome.duration_seconds, 3),
                         error=str(e)[:2000])  # fmt: skip
        shutil.rmtree(staging, ignore_errors=True)
        raise
    shutil.move(staging / "figure.png", folder / f"{name}.png")
    svg = None
    if (staging / "figure.svg").is_file():
        shutil.move(staging / "figure.svg", folder / f"{name}.svg")
        svg = f"{FIGURES_DIR}/{name}.svg"
    shutil.rmtree(staging, ignore_errors=True)

    index = load_index(root)
    index[name] = {"caption": caption, "png": f"{FIGURES_DIR}/{name}.png", "svg": svg,
                   "script": f"{FIGURES_DIR}/{name}.py", "log": f"{FIGURES_DIR}/{name}.log",
                   "plot_image_id": image_id, "drawn_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                   "data": [p.name for p in data]}  # fmt: skip
    (root / INDEX_FILE).write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    task.manifest["plot_image_id"] = image_id
    task.trace.event("figure_finished", name=name, ok=True, exit_code=0, png=f"{FIGURES_DIR}/{name}.png",
                     duration_seconds=round(outcome.duration_seconds, 3))  # fmt: skip
    return DrawnFigure(name, f"{FIGURES_DIR}/{name}.png", svg, f"{FIGURES_DIR}/{name}.py", png, output)
