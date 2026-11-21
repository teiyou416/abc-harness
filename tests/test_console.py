"""Live terminal output and the final metrics summary (console.Console, console.task_summary)."""

from __future__ import annotations

import io
import json

from doubles.fake_runner import FakeRunner
from doubles.scripted_model import ScriptedModel, run_last_proposed, text_turn, tool_turn
from test_literature import blocksim_plan

from abc_harness.agent.loop import run_agent_task
from abc_harness.execution.task import run_task
from abc_harness.execution.trace import Trace
from abc_harness.interfaces import console

SECRET = "sk-ant-console-secret"


def run_watched(tmp_path, steps):
    lines: list[str] = []
    screen = io.StringIO()
    model = ScriptedModel(steps)
    watcher = console.Console(lines.append, color=False, live=True, stream=screen, tick_seconds=0)
    result = run_agent_task("Compare block intervals.", model, FakeRunner(), lambda q: "", lambda plan: ("approve", ""),
                            runs_root=tmp_path / "runs", on_event=watcher)  # fmt: skip
    return result, lines, screen.getvalue()


def test_a_status_line_shows_the_current_action_and_milestones_stay(tmp_path):
    result, lines, screen = run_watched(tmp_path, [
        tool_turn("describe_simulator", {"simulator": "blocksim"}, text="Checking BlockSim first.",
                  thinking="BlockSim models block intervals directly; check its card."),
        tool_turn("propose_plan", blocksim_plan()),
        run_last_proposed,
        text_turn("Done."),
    ])  # fmt: skip
    assert result.status == "completed", result.stop_reason
    # Lasting lines: each tool call, the approval, and the final answer; not each model call or run.
    assert lines[:2] == ["● describe_simulator blocksim", "● propose_plan blocksim"]
    assert lines[2].startswith("✓ Plan ") and "approved (4 runs)" in lines[2]
    assert lines[3:] == ["● run_plan", "Done."]
    # The status line is redrawn in place (\r) and says what is happening now.
    drawn = [part.split(" · ")[0][2:] for part in screen.split("\r") if " · " in part]
    states = [s for i, s in enumerate(drawn) if i == 0 or s != drawn[i - 1]]
    assert states[:2] == ["Thinking", "Using describe_simulator blocksim"]
    assert "Using propose_plan blocksim" in states and "Running simulation 1/4" in states and "Running simulation 4/4" in states
    assert screen.endswith("\r\033[K")  # removed when the task ends
    trace = (result.artifact_dir / "trace.jsonl").read_text()
    for detail in ("BlockSim models block intervals directly", "Checking BlockSim first.", "stale_rate"):
        assert detail not in screen + "\n".join(lines) and detail in trace


def test_off_a_terminal_only_the_lasting_lines_are_written(tmp_path):
    lines: list[str] = []
    run_agent_task("q", ScriptedModel([text_turn("Done.")]), FakeRunner(), lambda q: "", lambda p: ("approve", ""),
                   runs_root=tmp_path / "runs", on_event=console.Console(lines.append, color=False, live=False))  # fmt: skip
    assert lines == ["Done."]


def test_the_status_line_is_removed_before_the_researcher_is_asked(tmp_path):
    screen = io.StringIO()
    watcher = console.Console(lambda line: None, color=False, live=True, stream=screen, tick_seconds=0)
    watcher({"event": "model_call_started", "call": 1})
    watcher({"event": "human_wait_started", "reason": "plan_review"})
    assert screen.getvalue().endswith("\r\033[K") and watcher.status == ""


def test_refused_tool_calls_are_marked(tmp_path):
    _, lines, screen = run_watched(tmp_path, [tool_turn("read_file", {"path": "/etc/passwd"}), text_turn("Stopping.")])
    assert "Using read_file /etc/passwd" in screen
    assert any(line.startswith("! read_file: ") and line != "! read_file: " for line in lines)


def test_the_listener_sees_events_after_redaction(tmp_path):
    seen = []
    trace = Trace(tmp_path / "trace.jsonl", redact=lambda s: s.replace(SECRET, "[redacted]"), listener=seen.append)
    trace.event("error", error=f"bad key {SECRET}")
    trace.close()
    assert seen == [json.loads((tmp_path / "trace.jsonl").read_text())]
    assert SECRET not in json.dumps(seen) and "[redacted]" in seen[0]["error"]


def test_summary_lists_run_statistics_not_results(tmp_path, write_plan):
    result = run_task(write_plan(), FakeRunner(), lambda plan: ("approve", ""), runs_root=tmp_path)
    summary = "\n".join(console.task_summary(result.artifact_dir))
    assert "── Run statistics of task" in summary and "Status: completed" in summary
    assert "Time: " in summary and "waiting for you" in summary
    runs = len(result.runs)
    assert f"Simulation runs: {runs} of {runs} completed" in summary and "Report: " in summary
    plan = json.loads((result.artifact_dir / "plan.json").read_text())
    assert not any(metric in summary for metric in plan["metrics"])  # results stay in report.md


def test_agent_summary_counts_model_calls_tokens_and_tools(tmp_path):
    result, _, _ = run_watched(tmp_path, [tool_turn("describe_simulator", {"simulator": "blocksim"}), text_turn("Done.")])
    summary = "\n".join(console.task_summary(result.artifact_dir))
    assert "Model: 2 calls of 500" in summary and "tokens 200 in" in summary
    assert "Tools: describe_simulator 1; 0 refused or failed" in summary


def test_every_tool_image_has_a_build_context():
    from abc_harness.interfaces.cli import TOOL_IMAGES

    for name, (context, _) in TOOL_IMAGES.items():
        assert (context / "Dockerfile").is_file(), name


def test_estimated_cost_prices_each_call_from_its_usage(tmp_path):
    from abc_harness.execution.trace import Trace

    trace = Trace(tmp_path / "trace.jsonl")
    usage = {"input_tokens": 50_000, "output_tokens": 30_000, "cache_read_input_tokens": 500_000,
             "cache_creation_input_tokens": 20_000}  # fmt: skip
    trace.event("model_call", model="claude-opus-5-5", usage=usage)
    trace.event("compaction", usage={"input_tokens": 10_000, "output_tokens": 1_000})  # priced as the task's model
    trace.close()
    # 0.05*4 + 0.03*20 + 0.5*0.20 + 0.02*5 = 1.00; the summary call: 0.01*4 + 0.001*20 = 0.06
    total, priced, unknown = console.estimated_cost(tmp_path / "trace.jsonl", "claude-opus-5-5")
    assert round(total, 6) == 1.06 and priced == {"claude-opus-5-5"} and unknown == set()
    line = console.estimated_cost_line(tmp_path / "trace.jsonl", "claude-opus-5-5")
    assert line == "Estimated cost: $1.06 at list prices for claude-opus-5-5 (an estimate, not a bill)"


def test_unknown_models_are_named_not_guessed(tmp_path):
    result, _, _ = run_watched(tmp_path, [text_turn("Done.")])
    summary = "\n".join(console.task_summary(result.artifact_dir))
    assert "Estimated cost: unknown (no list price for scripted)" in summary


def test_prices_cover_the_listed_models_haiku_tiers_and_deepseek_hours():
    from datetime import UTC, datetime

    from abc_harness.agent.model import MODELS, price_for

    assert all(price_for(name) for name in MODELS) and price_for("claude-opus-4-5") is None
    assert price_for("claude-opus-5-5").input == 4.0 and price_for("claude-sonnet-5-5").cache_read == 0.10
    haiku = price_for("claude-haiku-5-5")
    small = {"input_tokens": 1_000, "cache_read_input_tokens": 99_000, "output_tokens": 1_000}
    large = {**small, "cache_read_input_tokens": 99_001}  # one token over 100,000 in the prompt
    assert round(haiku.cost(small), 6) == round((1_000 * 0.10 + 99_000 * 0.01 + 1_000 * 0.50) / 1e6, 6)
    assert round(haiku.cost(large), 6) == round((1_000 * 0.50 + 99_001 * 0.05 + 1_000 * 2.50) / 1e6, 6)

    flash = price_for("deepseek-flash")
    usage = {"input_tokens": 1_000_000, "cache_read_input_tokens": 1_000_000, "output_tokens": 1_000_000}
    peak = datetime(2026, 11, 19, 7, 0, tzinfo=UTC)  # Thursday 07:00 UTC
    night = datetime(2026, 11, 19, 15, 0, tzinfo=UTC)
    saturday = datetime(2026, 11, 21, 7, 0, tzinfo=UTC)
    assert round(flash.cost(usage, peak), 6) == round(0.30 + 0.006 + 1.20, 6)
    assert round(flash.cost(usage, night), 6) == round((0.30 + 0.006 + 1.20) / 2, 6)
    assert flash.cost(usage, saturday) == flash.cost(usage, night)
