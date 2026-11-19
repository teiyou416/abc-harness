"""Live terminal output and the final metrics summary (cli.Console, cli.task_summary)."""

from __future__ import annotations

import json

from doubles.fake_runner import FakeRunner
from doubles.scripted_model import ScriptedModel, run_last_proposed, text_turn, tool_turn
from test_literature import blocksim_plan

from abc_harness import cli
from abc_harness.agent.loop import run_agent_task
from abc_harness.execution.task import run_task
from abc_harness.execution.trace import Trace

SECRET = "sk-ant-console-secret"


def run_watched(tmp_path, steps):
    lines: list[str] = []
    model = ScriptedModel(steps)
    result = run_agent_task("Compare block intervals.", model, FakeRunner(), lambda q: "", lambda plan: ("approve", ""),
                            runs_root=tmp_path / "runs", on_event=cli.Console(lines.append, color=False))  # fmt: skip
    return result, lines


def test_console_shows_thinking_tool_calls_results_and_runs(tmp_path):
    result, lines = run_watched(tmp_path, [
        tool_turn("describe_simulator", {"simulator": "blocksim"}, text="Checking BlockSim first.",
                  thinking="BlockSim models block intervals directly; check its card."),
        tool_turn("propose_plan", blocksim_plan()),
        run_last_proposed,
        text_turn("Done."),
    ])  # fmt: skip
    assert result.status == "completed", result.stop_reason
    text = "\n".join(lines)
    assert "… model call 1: waiting for the model" in text
    assert "◆ model call 1:" in text
    assert "  thinking: BlockSim models block intervals directly; check its card." in text
    assert "  says: Checking BlockSim first." in text
    assert '  → describe_simulator {"simulator": "blocksim"}' in text
    assert "  ← describe_simulator ok (" in text
    assert "▣ researcher decided approve" in text
    assert "▶ simulation run base__seed-1 started" in text
    assert "base__seed-1: completed in" in text and "stale_rate=" in text
    assert text.index("thinking:") < text.index("← describe_simulator")


def test_refused_tool_calls_are_marked(tmp_path):
    _, lines = run_watched(tmp_path, [tool_turn("read_file", {"path": "/etc/passwd"}), text_turn("Stopping.")])
    assert any(line.startswith("! ← read_file error") for line in lines)


def test_the_listener_sees_events_after_redaction(tmp_path):
    seen = []
    trace = Trace(tmp_path / "trace.jsonl", redact=lambda s: s.replace(SECRET, "[redacted]"), listener=seen.append)
    trace.event("error", error=f"bad key {SECRET}")
    trace.close()
    assert seen == [json.loads((tmp_path / "trace.jsonl").read_text())]
    assert SECRET not in json.dumps(seen) and "[redacted]" in seen[0]["error"]


def test_summary_lists_run_statistics_not_results(tmp_path, write_plan):
    result = run_task(write_plan(), FakeRunner(), lambda plan: ("approve", ""), runs_root=tmp_path)
    summary = "\n".join(cli.task_summary(result.artifact_dir))
    assert "── Run statistics of task" in summary and "Status: completed" in summary
    assert "Time: " in summary and "waiting for you" in summary
    runs = len(result.runs)
    assert f"Simulation runs: {runs} of {runs} completed" in summary and "Report: " in summary
    plan = json.loads((result.artifact_dir / "plan.json").read_text())
    assert not any(metric in summary for metric in plan["metrics"])  # results stay in report.md


def test_agent_summary_counts_model_calls_tokens_and_tools(tmp_path):
    result, _ = run_watched(tmp_path, [tool_turn("describe_simulator", {"simulator": "blocksim"}), text_turn("Done.")])
    summary = "\n".join(cli.task_summary(result.artifact_dir))
    assert "Model: 2 calls of 500" in summary and "tokens 200 in" in summary
    assert "Tools: describe_simulator 1; 0 refused or failed" in summary
