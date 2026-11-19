"""Chat sessions: one task per request, the harness-written memory of earlier tasks, and the REPL."""

from __future__ import annotations

import json
import re

import pytest
from doubles.fake_runner import FakeRunner
from doubles.scripted_model import ScriptedModel, last_tool_result, run_last_proposed, text_turn, tool_turn
from test_literature import blocksim_plan

from abc_harness.agent.session import ChatSession
from abc_harness.interfaces.chat import HELP, ModelControl, run_chat


class Inputs:
    """Answers prompts in order; raises what a test puts in the list (EOFError, KeyboardInterrupt)."""

    def __init__(self, *lines):
        self.lines = list(lines)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        item = self.lines.pop(0) if self.lines else EOFError()
        if isinstance(item, BaseException):
            raise item
        return item


def experiment(answer="The 60 s delay raised the stale rate."):
    return [tool_turn("propose_plan", blocksim_plan()), run_last_proposed, text_turn(answer)]


def chat(tmp_path, model, inputs, runner=None, show_answers=True):
    runner = runner or FakeRunner()
    out = []
    sessions = []

    def new_session():
        sessions.append(ChatSession(tmp_path / "runs"))
        return sessions[-1]

    def review(plan):
        return inputs("Approve? "), ""

    def turn(session, text):
        return session.run_turn(text, model, runner, lambda q: inputs(f"Q: {q} "), review)

    status = run_chat(new_session, turn, inputs, out.append, parser_check=lambda: None, show_answers=show_answers)
    return status, out, sessions


def first_message(model, call):
    return model.calls[call][0]["content"]


def earlier_task_id(messages):
    return re.search(r"### Task 1: `([^`]+)`", messages[0]["content"]).group(1)


def test_each_request_is_a_task_and_the_next_one_remembers_it(tmp_path):
    model = ScriptedModel([*experiment(), tool_turn("read_file", {"path": "x"}), text_turn("Base was lower.")])
    inputs = Inputs("Does delay raise the stale rate?", "approve", "Which configuration was lower?", "/quit")
    status, out, (session,) = chat(tmp_path, model, inputs)
    assert status == 0
    assert [t.status for t in session.turns] == ["completed", "not_executed"]
    first, second = session.turns
    assert first.artifact_dir != second.artifact_dir and (second.artifact_dir / "report.md").exists()

    memory = first_message(model, 3)
    assert memory.startswith("Which configuration was lower?")
    assert f"### Task 1: `{first.task_id}` (completed" in memory
    assert "Researcher asked: Does delay raise the stale rate?" in memory
    assert "Plan run: Delay and stale rate (blocksim; configurations base, slow" in memory
    assert "- base: stale_rate 0.2000 ± 0.0000 (n=2)" in memory
    assert "Your final answer then: The 60 s delay raised the stale rate." in memory
    assert "find a paper again with search_papers" in memory

    manifest = json.loads((second.artifact_dir / "manifest.json").read_text())
    assert manifest["session_id"] == session.session_id and manifest["previous_tasks"] == [first.task_id]
    log = [json.loads(line) for line in (session.dir / "session.jsonl").read_text().splitlines()]
    assert [(e["turn"], e["task_id"]) for e in log] == [(1, first.task_id), (2, second.task_id)]
    assert "The 60 s delay raised the stale rate." in [line.strip() for line in out]
    assert any("── Run statistics" in line for line in out)


def test_earlier_tasks_are_readable_under_previous_and_nothing_else_is(tmp_path):
    def read(path):
        return tool_turn("read_file", {"path": path, "limit": 3})

    model = ScriptedModel([
        text_turn("First answer."),
        lambda m: read(f"previous/{earlier_task_id(m)}/report.md"),
        read("previous/20200101-000000-abcdef/report.md"),
        lambda m: read(f"previous/{earlier_task_id(m)}/../../../.env"),
        text_turn("Done."),
    ])  # fmt: skip
    chat(tmp_path, model, Inputs("hello", "what did you say?", "/quit"))
    assert "# Task without an executed plan" in model.calls[2][-1]["content"][0]["content"]
    assert "earlier tasks of this conversation" in model.calls[3][-1]["content"][0]["content"]
    assert "is outside previous/" in model.calls[4][-1]["content"][0]["content"]


def test_only_the_latest_tasks_are_shown_in_full(tmp_path):
    session = ChatSession(tmp_path / "runs")
    model = ScriptedModel([text_turn(f"answer {i}") for i in range(7)])
    for i in range(7):
        session.run_turn(f"question {i}", model, FakeRunner(), lambda q: "", lambda p: ("approve", ""))
    memory = session.preface()
    assert "Older tasks:" in memory and "- Task 1 `" in memory and "question 0" in memory
    assert memory.count("### Task") == 5 and "### Task 7:" in memory


def test_slash_commands(tmp_path):
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    text = tmp_path / "notes.pdf"
    text.write_text("not a pdf")
    model = ScriptedModel([text_turn("Hi.")])
    inputs = Inputs("/help", "/tasks", f"/paper {pdf}", f"/paper {text}", "/paper", "/bogus", "hello", "/tasks",
                    "/new", "/tasks", "/exit")  # fmt: skip
    status, out, sessions = chat(tmp_path, model, inputs)
    assert status == 0 and len(sessions) == 2
    joined = "\n".join(out)
    assert HELP in out and "No task yet in this conversation." in out
    assert "Added paper.pdf; every following task in this conversation reads it." in out
    assert "not a PDF file" in joined and "usage: /paper <file.pdf>" in joined and "unknown command /bogus" in joined
    assert "1. " in joined and "not_executed  scripted-model  hello" in joined and "Papers: paper.pdf" in joined
    assert sessions[1].turns == [] and sessions[1].papers == []
    assert sessions[0].turns[0].artifact_dir.joinpath("papers", "local-paper.pdf").exists()


def test_ctrl_c_during_a_task_stops_it_and_the_chat_continues(tmp_path):
    def press_ctrl_c(run_id, workdir):
        if run_id == "slow__seed-1":
            raise KeyboardInterrupt

    runner = FakeRunner(inspect=press_ctrl_c)
    model = ScriptedModel([*experiment()[:2], text_turn("Still here.")])
    inputs = Inputs("Run it.", "approve", "Are you there?", "/quit")
    status, out, (session,) = chat(tmp_path, model, inputs, runner=runner)
    assert status == 0
    interrupted, after = session.turns
    assert interrupted.status == "failed" and "interrupted" in interrupted.stop_reason
    assert (interrupted.artifact_dir / "report.md").exists() and runner.cleanups == [interrupted.task_id]
    assert any("Stopped the task" in line for line in out)
    assert after.status == "not_executed" and f"`{interrupted.task_id}` (failed" in model.calls[-1][0]["content"]


@pytest.mark.parametrize("leave", [EOFError(), KeyboardInterrupt()])
def test_ctrl_d_or_ctrl_c_at_the_prompt_leaves(tmp_path, leave):
    status, out, _ = chat(tmp_path, ScriptedModel([]), Inputs("", leave))
    assert status == 0 and out[-1] == "Bye."


def test_plan_review_and_questions_use_the_chat_input(tmp_path):
    model = ScriptedModel([
        tool_turn("ask_researcher", {"question": "Which delay?"}),
        lambda messages: text_turn(f"You said {last_tool_result(messages)['content']}"),
    ])  # fmt: skip
    inputs = Inputs("Plan something.", "60 seconds", "/quit")
    _, out, _ = chat(tmp_path, model, inputs)
    assert "Q: Which delay? " in inputs.prompts
    assert any("60 seconds" in line for line in out)


def test_with_live_output_the_answer_is_printed_once(tmp_path):
    from abc_harness.interfaces.console import Console

    out = []
    model = ScriptedModel([tool_turn("describe_simulator", {"simulator": "blocksim"}, text="Checking."),
                           text_turn("BlockSim and SimBlock.")])  # fmt: skip

    def turn(session, text):
        return session.run_turn(text, model, FakeRunner(), lambda q: "", lambda p: ("approve", ""),
                                on_event=Console(out.append, color=False))  # fmt: skip

    run_chat(lambda: ChatSession(tmp_path / "runs"), turn, Inputs("Which simulators?", "/quit"), out.append)
    assert [line.strip() for line in out].count("BlockSim and SimBlock.") == 1
    assert "  says: Checking." in out  # text before a tool call stays a note


def test_model_command_shows_and_switches_the_model_for_following_tasks(tmp_path):
    current = {"name": "claude-opus-5-5"}

    def switch(name):
        if name == "claude-opus-4-5-20251101":
            return "claude-opus-4-5-20251101 has no adaptive thinking, which the harness's requests use"
        current["name"] = name
        return None

    models = ModelControl(lambda: current["name"], switch, lambda: ["claude-opus-5-5", "claude-sonnet-5-5"])
    model = ScriptedModel([text_turn("Hi.")])
    used = []

    def turn(session, text):
        model.name = current["name"]
        used.append(model.name)
        return session.run_turn(text, model, FakeRunner(), lambda q: "", lambda p: ("approve", ""))

    out = []
    inputs = Inputs("/model", "/model claude-opus-4-5-20251101", "/model claude-sonnet-5-5", "hello", "/tasks", "/quit")
    run_chat(lambda: ChatSession(tmp_path / "runs"), turn, inputs, out.append, models=models)
    joined = "\n".join(out)
    assert "Model: claude-opus-5-5\nAvailable: claude-opus-5-5, claude-sonnet-5-5" in joined
    assert "! claude-opus-4-5-20251101 has no adaptive thinking" in joined
    assert "The following tasks use claude-sonnet-5-5. (no list price known" in joined
    assert used == ["claude-sonnet-5-5"] and "not_executed  claude-sonnet-5-5  hello" in joined
