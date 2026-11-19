"""Helpers for figure scripts run by the make_figure tool, inside the plot image.

The task's results are mounted read-only at /data; the figure goes to /out.
Use these helpers instead of typing numbers into a script:

    import abcplot
    abcplot.use_style()
    stats = abcplot.summary("stale_rate")            # {configuration: (mean, sd, n)}
    fig, ax = abcplot.figure()
    ...
    abcplot.save(fig)                                 # writes /out/figure.svg and /out/figure.png

Style rules (the harness's version of good figure practice): no title (the
caption is the title), axis labels with units, error bars with the seed count
stated, a colour-blind-safe palette, and the same sans-serif font everywhere.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

DATA = Path("/data")
OUT = Path("/out")
# Okabe-Ito: distinguishable with the common colour-vision deficiencies.
PALETTE = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#F0E442", "#000000"]
MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*"]
COLUMN, TEXT = 3.25, 6.75  # inches: one column and full text width of a two-column paper


def use_style() -> None:
    plt.rcParams.update({
        "font.family": "sans-serif", "font.size": 8, "axes.labelsize": 8, "legend.fontsize": 7,
        "xtick.labelsize": 7, "ytick.labelsize": 7, "axes.spines.top": False, "axes.spines.right": False,
        "axes.prop_cycle": plt.cycler(color=PALETTE), "lines.linewidth": 1.4, "lines.markersize": 4,
        "errorbar.capsize": 2, "savefig.bbox": "tight", "svg.fonttype": "none",
    })  # fmt: skip


def figure(width: float = COLUMN, height: float | None = None, **kwargs: Any) -> tuple[Any, Any]:
    """A figure at its final printed size, so no text is scaled down later."""
    return plt.subplots(figsize=(width, height or width * 0.68), **kwargs)


def plan() -> dict[str, Any]:
    """The executed plan: configurations, baseline, metrics, seeds."""
    return json.loads((DATA / "plan.json").read_text(encoding="utf-8"))


def runs(completed_only: bool = True) -> list[dict[str, Any]]:
    """Every simulation run from results.json: run_id, configuration, seed, params, status, metrics."""
    rows = json.loads((DATA / "results.json").read_text(encoding="utf-8"))
    return [r for r in rows if r["status"] == "completed"] if completed_only else rows


def params(configuration: str) -> dict[str, Any]:
    """The full parameters of a configuration: the baseline with its own changes."""
    p = plan()
    config = next(c for c in p["configurations"] if c["name"] == configuration)
    return {**p.get("baseline", {}), **config.get("params", {})}


def summary(metric: str) -> dict[str, tuple[float, float, int]]:
    """Per configuration, in plan order: (mean, sample standard deviation or 0 for one run, n)."""
    out = {}
    for config in plan()["configurations"]:
        values = [r["metrics"][metric] for r in runs() if r["configuration"] == config["name"] and metric in r["metrics"]]
        if values:
            sd = statistics.stdev(values) if len(values) > 1 else 0.0
            out[config["name"]] = (statistics.fmean(values), sd, len(values))
    return out


def save(fig: Any, stem: str = "figure") -> None:
    """Write the figure as SVG (vector, for papers) and PNG (for the report and the agent to look at)."""
    fig.savefig(OUT / f"{stem}.svg")
    fig.savefig(OUT / f"{stem}.png", dpi=200)
    plt.close(fig)
