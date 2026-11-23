from __future__ import annotations

import json

import pytest
from doubles.fake_runner import FakeRunner
from doubles.scripted_model import ScriptedModel, run_last_proposed, text_turn, tool_turn
from test_literature import blocksim_plan

from abc_harness.agent.judge import (
    JUDGE_CALLS,
    JudgeRefused,
    default_model,
    judge,
    parse_verdict,
    prepare,
    rubric_hash,
)
from abc_harness.agent.model import ModelDeadlineExceeded
from abc_harness.agent.session import ChatSession
from abc_harness.interfaces.chat import judge_task, run_chat
from abc_harness.interfaces.console import task_summary

ANSWER = "The 60 s delay clearly raised the stale rate from 0.20 to 0.30."
VERDICT = json.dumps({"conclusion_supported": 4, "reason": "Two runs cannot support 'clearly'.",
                      "faulted": ["The 60 s delay clearly raised the stale rate from 0.20 to 0.30."]})


def finished_task(tmp_path, answer=ANSWER):
    """An agent task that executed a plan (fake runner) and ended with `answer`."""
    session = ChatSession(tmp_path / "runs")
    agent = ScriptedModel([tool_turn("propose_plan", blocksim_plan()), run_last_proposed, text_turn(answer)])
    turn = session.run_turn("Does delay raise the stale rate?", agent, FakeRunner(), lambda q: "",
                            lambda p: ("approve", ""))  # fmt: skip
    return session, turn.artifact_dir


def judge_model(*replies):
    model = ScriptedModel([r if not isinstance(r, str) else text_turn(r) for r in replies])
    model.name = "claude-sonnet-5-5"
    return model


def records(task_dir):
    return [json.loads(line) for line in (task_dir / "judge.jsonl").read_text().splitlines()]


def test_the_judge_sees_the_saved_evidence_and_its_verdict_is_recorded(tmp_path):
    _, task_dir = finished_task(tmp_path)
    before = {p.name: p.read_bytes() for p in task_dir.iterdir() if p.is_file()}
    model = judge_model(VERDICT)
    record = judge(prepare(task_dir), model)

    (message,) = model.calls[0]
    text = message["content"]
    assert "Does delay raise the stale rate?" in text and ANSWER in text
    assert "## Results" in text and "PASS:" in text  # the harness tables and the evidence check
    assert model.requests[0]["tools"] == [] and model.requests[0]["system"].startswith("You are a strict")
    assert record["status"] == "scored" and record["score"] == 4 and record["faulted"] == [ANSWER]
    assert record["judge_model"] == "scripted" and record["task_model"] == "scripted-model"
    assert record["rubric_sha256"] == rubric_hash() and record["model_calls"] == 1
    assert record["label"] == "model-assessed advice, not evidence"
    assert records(task_dir) == [record]
    after = {p.name: p.read_bytes() for p in task_dir.iterdir() if p.is_file() and p.name != "judge.jsonl"}
    assert after == before  # the judgment changes no artifact of the task

    summary = "\n".join(task_summary(task_dir))
    assert "Judge (scripted, model-assessed): conclusion_supported 4/10. Two runs cannot support" in summary
    assert f'faulted: "{ANSWER}"' in summary


def test_an_unreadable_verdict_is_retried_once_then_recorded_as_no_verdict(tmp_path):
    _, task_dir = finished_task(tmp_path)
    model = judge_model("I think it is fine.", VERDICT)
    assert judge(prepare(task_dir), model)["status"] == "scored"
    assert "could not be read" in model.calls[1][-1]["content"]

    record = judge(prepare(task_dir), judge_model("no json", '{"conclusion_supported": "high"}'))
    assert record["status"] == "no_verdict" and record["score"] is None and record["model_calls"] == JUDGE_CALLS
    assert len(records(task_dir)) == 2  # every judgment is kept, the latest last
    assert "no verdict" in "\n".join(task_summary(task_dir))


def test_a_reply_cut_at_the_output_limit_says_so(tmp_path):
    _, task_dir = finished_task(tmp_path)
    cut = text_turn("Let me check each number first...", stop_reason="max_tokens")
    record = judge(prepare(task_dir), judge_model(cut, cut))
    assert record["status"] == "no_verdict" and "cut at the 16,384-token output limit" in record["reason"]


def test_a_judge_that_times_out_is_recorded_as_an_error(tmp_path):
    _, task_dir = finished_task(tmp_path)

    def too_slow(_messages):
        raise ModelDeadlineExceeded("slow")

    record = judge(prepare(task_dir), judge_model(too_slow))
    assert record["status"] == "error" and "within 120 seconds" in record["reason"]


def test_tasks_that_cannot_be_judged_are_refused(tmp_path):
    session = ChatSession(tmp_path / "runs")
    reply = session.run_turn("hi", ScriptedModel([text_turn("Hello.")]), FakeRunner(), lambda q: "",
                             lambda p: ("approve", ""))  # fmt: skip
    with pytest.raises(JudgeRefused, match="executed no plan"):
        prepare(reply.artifact_dir)

    _, task_dir = finished_task(tmp_path / "b")
    check = json.loads((task_dir / "trace_check.json").read_text())
    check["lines"].append("FAIL: raw/base__seed-1/stale_rate: raw value 0.2 differs from results.json (0.3)")
    (task_dir / "trace_check.json").write_text(json.dumps(check))
    with pytest.raises(JudgeRefused, match="evidence check found contradictions.*raw value 0.2"):
        prepare(task_dir)


def test_the_default_judge_is_another_model_with_a_key():
    keys = {"ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"}
    assert default_model("deepseek-flash", lambda k: k in keys) == "claude-sonnet-5-5"
    assert default_model("claude-sonnet-5-5", lambda k: k in keys) == "deepseek-v4-pro"
    assert default_model("claude-sonnet-5-5", lambda k: k == "ANTHROPIC_API_KEY") == "claude-opus-5-5"
    assert default_model("x", lambda k: False) is None


@pytest.mark.parametrize(("text", "expected"), [
    ('Sure: {"conclusion_supported": 7.6, "reason": "ok", "faulted": []}', 8),
    ('{"conclusion_supported": 14, "reason": "", "faulted": ["a", 3]}', 10),
    ('{"conclusion_supported": true, "reason": ""}', None),
    ('{"score": 5}', None),
    ("no object", None),
])  # fmt: skip
def test_verdicts_are_parsed_strictly(text, expected):
    verdict = parse_verdict(text)
    assert (verdict["score"] if verdict else None) == expected
    if verdict and expected == 10:
        assert verdict["faulted"] == ["a"]


def test_judging_shows_the_cost_first_and_can_be_declined(tmp_path):
    _, task_dir = finished_task(tmp_path)
    out = []
    model = judge_model(VERDICT)
    code = judge_task(task_dir, None, lambda name: model, lambda k: k == "ANTHROPIC_API_KEY", lambda: False,
                      lambda s: s, out.append)  # fmt: skip
    assert code == 0 and out[-1] == "Not judged." and not (task_dir / "judge.jsonl").exists()
    assert out[0].startswith(f"Judge {task_dir.name} with claude-sonnet-5-5, effort low: about $")
    assert model.calls == []

    out.clear()
    assert judge_task(task_dir, None, lambda name: model, lambda k: True, lambda: True, lambda s: s, out.append) == 0
    assert any("conclusion_supported 4/10" in line for line in out)


def test_judge_in_chat_takes_the_latest_task_with_a_plan_or_a_number(tmp_path):
    session, task_dir = finished_task(tmp_path)
    session.run_turn("thanks", ScriptedModel([text_turn("You're welcome.")]), FakeRunner(), lambda q: "",
                     lambda p: ("approve", ""))  # fmt: skip
    judged, out = [], []
    inputs = iter(["/judge", "/judge 2", "/judge 9", "/quit"])
    run_chat(lambda: session, lambda s, t: None, lambda _p: next(inputs), out.append, judge=judged.append)
    assert judged == [task_dir, session.turns[1].artifact_dir]
    assert "! /judge takes a task number from /tasks (1 to 2), not '9'" in out


def test_an_answer_with_its_own_headings_is_judged_and_checked_whole(tmp_path):
    answer = "The 60 s delay raised the stale rate.\n\n## Limitations\n\nOnly 2 runs; the true rate may be 0.47."
    _, task_dir = finished_task(tmp_path, answer)
    assert (task_dir / "answer.md").read_text().strip() == answer
    message = prepare(task_dir).message
    assert "## Limitations\n\nOnly 2 runs; the true rate may be 0.47." in message.split("The agent's final answer")[1]
    lines = json.loads((task_dir / "trace_check.json").read_text())["lines"]
    assert any(line.startswith("WARN") and "0.47" in line for line in lines)  # the answer is no source for itself
