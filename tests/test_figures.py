"""make_figure: the agent's figure scripts, run in the plot image (FakeRunner here; test_docker.py runs the real one)."""

from __future__ import annotations

import json

import pytest
from doubles.fake_runner import FakeClock, FakeRunner
from doubles.scripted_model import ScriptedModel, last_tool_result, run_last_proposed, text_turn, tool_turn
from test_literature import blocksim_plan

from abc_harness.agent.context import task_state
from abc_harness.agent.loop import run_agent_task
from abc_harness.execution.figures import PLOT_IMAGE
from abc_harness.execution.limits import Budget
from abc_harness.execution.trace import read_trace

SCRIPT = """import abcplot
abcplot.use_style()
stats = abcplot.summary("stale_rate")
fig, ax = abcplot.figure()
names = list(stats)
ax.errorbar(range(len(names)), [stats[n][0] for n in names], yerr=[stats[n][1] for n in names], fmt="o")
ax.set_xticks(range(len(names)), names)
ax.set_ylabel("Stale rate (fraction of blocks)")
abcplot.save(fig)
"""
CAPTION = "Stale rate per configuration; mean ± sample standard deviation over 2 seeds."


def figure_call(name="stale-rate", script=SCRIPT, caption=CAPTION):
    return tool_turn("make_figure", {"name": name, "script": script, "caption": caption})


def run(tmp_path, steps, runner=None, budget=None):
    runner = runner or FakeRunner()
    model = ScriptedModel(steps)
    result = run_agent_task("Does delay raise the stale rate?", model, runner, lambda q: "", lambda p: ("approve", ""),
                            runs_root=tmp_path / "runs", budget=budget)  # fmt: skip
    return result, model, runner


def after_run(*steps):
    return [tool_turn("propose_plan", blocksim_plan()), run_last_proposed, *steps]


def said(model, call):
    return model.calls[call][-1]["content"][0]["content"]


def test_the_agent_draws_sees_and_reports_a_figure(tmp_path):
    result, model, runner = run(tmp_path, after_run(figure_call(), text_turn("See figure stale-rate.")))
    assert result.status == "completed", result.stop_reason
    sent = model.calls[3][-1]["content"][0]["content"]
    assert [b["type"] for b in sent] == ["text", "image"] and sent[1]["source"]["media_type"] == "image/png"
    assert "[figure stale-rate: saved task/figures/stale-rate.png and task/figures/stale-rate.svg" in sent[0]["text"]

    call = runner.plot_calls[0]
    assert call["script"] == SCRIPT
    assert call["data"] == ["plan.json", "raw", "results.json"]  # only this task's results
    assert {r["status"] for r in call["results"]} == {"completed"}  # results.json was current when drawn

    task_dir = result.artifact_dir
    for suffix in ("png", "svg", "py", "log"):
        assert (task_dir / "figures" / f"stale-rate.{suffix}").exists()
    assert not list((task_dir / "figures").glob(".out-*"))
    index = json.loads((task_dir / "figures" / "index.json").read_text())
    assert index["stale-rate"]["caption"] == CAPTION and index["stale-rate"]["plot_image_id"].startswith("sha256:")
    report = (task_dir / "report.md").read_text()
    assert f"![{CAPTION}](figures/stale-rate.png)" in report
    assert "script: [figures/stale-rate.py](figures/stale-rate.py) · [SVG](figures/stale-rate.svg)" in report
    manifest = json.loads((task_dir / "manifest.json").read_text())
    assert manifest["plot_image_id"] == index["stale-rate"]["plot_image_id"]
    events = [e for e in read_trace(task_dir / "trace.jsonl") if e["event"].startswith("figure_")]
    assert [(e["event"], e.get("ok")) for e in events] == [("figure_started", None), ("figure_finished", True)]


def test_redrawing_with_the_same_name_replaces_the_figure(tmp_path):
    fixed = SCRIPT.replace("Stale rate (fraction of blocks)", "Stale rate (share of blocks)")
    result, _, runner = run(tmp_path, after_run(figure_call(), figure_call(script=fixed, caption="Fixed."),
                                                text_turn("Done.")))  # fmt: skip
    index = json.loads((result.artifact_dir / "figures" / "index.json").read_text())
    assert list(index) == ["stale-rate"] and index["stale-rate"]["caption"] == "Fixed."
    assert (result.artifact_dir / "figures" / "stale-rate.py").read_text() == fixed
    assert len(runner.plot_calls) == 2


def test_figures_need_an_executed_plan(tmp_path):
    _, model, runner = run(tmp_path, [figure_call(), lambda m: text_turn(last_tool_result(m)["content"])])
    assert "after run_plan" in said(model, 1) and runner.plot_calls == []


@pytest.mark.parametrize(("behaviour", "message"), [
    ("fail", "failed with exit code 1:\nTraceback"),
    ("no_output", "wrote no /out/figure.png"),
    ("timeout", "did not finish within 120s"),
])  # fmt: skip
def test_script_failures_go_back_to_the_agent(tmp_path, behaviour, message):
    runner = FakeRunner(plot_behaviour=behaviour)
    result, model, _ = run(tmp_path, after_run(figure_call(), text_turn("Gave up.")), runner=runner)
    assert result.status == "completed"  # a failed figure does not undo the experiment
    error = said(model, 3)
    assert error.startswith("figure 'stale-rate' was not drawn") and message in error
    assert not (result.artifact_dir / "figures" / "stale-rate.png").exists()
    assert (result.artifact_dir / "figures" / "stale-rate.log").exists()
    assert "## Figures" not in (result.artifact_dir / "report.md").read_text()


@pytest.mark.parametrize(("args", "message"), [
    ({"name": "Bad Name"}, "lowercase letters"),
    ({"caption": ""}, "caption must be"),
    ({"script": " "}, "script must be"),
])  # fmt: skip
def test_bad_requests_are_refused(tmp_path, args, message):
    call = tool_turn("make_figure", {"name": "stale-rate", "script": SCRIPT, "caption": CAPTION, **args})
    _, model, runner = run(tmp_path, after_run(call, text_turn("Done.")))
    assert message in said(model, 3) and runner.plot_calls == []


def test_without_the_plot_image_the_tool_says_how_to_build_it(tmp_path):
    runner = FakeRunner(missing_images={PLOT_IMAGE})
    _, model, _ = run(tmp_path, after_run(figure_call(), text_turn("Done.")), runner=runner)
    assert "abc-harness image build" in said(model, 3)


def test_drawing_time_counts_and_a_budget_timeout_stops_the_task(tmp_path):
    clock = FakeClock()
    runner = FakeRunner(clock=clock, plot_behaviour="timeout")
    budget = Budget(time_limit_seconds=10, clock=clock)  # the plan's 4 runs use 4 s; the figure gets the rest
    result, _, _ = run(tmp_path, after_run(figure_call(), text_turn("Done.")), runner=runner, budget=budget)
    assert result.status == "stopped_by_limit" and "while drawing figure stale-rate" in result.stop_reason
    assert all(r.status == "completed" for r in result.runs)  # the simulation results are kept


def test_the_task_state_lists_drawn_figures(tmp_path):
    result, _, _ = run(tmp_path, after_run(figure_call(), text_turn("Done.")))

    class Done:
        artifact_dir, plans, executed = result.artifact_dir, {}, None

    state = task_state(Done(), [])  # type: ignore[arg-type]
    assert "- `stale-rate`: task/figures/stale-rate.png, script task/figures/stale-rate.py" in state


def test_a_model_that_cannot_see_images_gets_the_figure_saved_but_not_shown(tmp_path):
    model = ScriptedModel(after_run(figure_call(), tool_turn("view_figure", {"paper": "x", "figure": "Figure 1"}),
                                    text_turn("Done.")))  # fmt: skip
    model.sees_images = False
    result = run_agent_task("q", model, FakeRunner(), lambda q: "", lambda p: ("approve", ""), runs_root=tmp_path / "runs")
    drawn = model.calls[3][-1]["content"][0]["content"]
    assert isinstance(drawn, str) and "cannot see images, so the figure is saved and in the report" in drawn
    assert (result.artifact_dir / "figures" / "stale-rate.png").exists()
    assert "cannot see images, so it cannot read a figure" in model.calls[4][-1]["content"][0]["content"]
