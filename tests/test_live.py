"""Calls the real Claude API. Run with `make test-live`; needs ANTHROPIC_API_KEY in .env.

The researcher's side rejects the first plan, so no simulator runs and the cost
stays at a few model calls. The test checks that a real model drafts a plan the
harness accepts and that the key never reaches the trace.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from doubles.fake_runner import FakeRunner

from abc_harness.agent.loop import run_agent_task
from abc_harness.agent.model import AnthropicModel
from abc_harness.agent.secrets import Secrets
from abc_harness.execution.limits import Budget
from abc_harness.execution.trace import read_trace

pytestmark = pytest.mark.live
ROOT = Path(__file__).resolve().parents[1]


def test_real_model_drafts_a_valid_plan(tmp_path):
    secrets = Secrets.load(ROOT / ".env")
    if not secrets.has("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set in .env")
    key = secrets.get("ANTHROPIC_API_KEY")
    reviewed = []

    def reject_after_review(plan):
        reviewed.append(plan)
        return "reject", "live test: stop before running"

    result = run_agent_task(
        "With 300 nodes and 100 blocks in SimBlock, does a 30 s block interval produce more orphans than 600 s?",
        AnthropicModel(key),
        FakeRunner(),
        lambda question: "Use your defaults.",
        reject_after_review,
        runs_root=tmp_path / "runs",
        budget=Budget(llm_call_limit=15),
        redact=secrets.redact,
    )
    assert result.status == "rejected", result.stop_reason
    assert len(reviewed) == 1
    assert reviewed[0].simulator == "simblock"
    assert key not in (result.artifact_dir / "trace.jsonl").read_text()
    # The model's reasoning summaries reach the saved trace.
    calls = [e for e in read_trace(result.artifact_dir / "trace.jsonl") if e["event"] == "model_call"]
    assert any(c.get("thinking") for c in calls)


def test_real_model_compresses_and_continues(tmp_path):
    """A tiny soft limit forces one real summary call; the agent must keep working in the new window."""
    import json

    from abc_harness.agent.context import ContextLimits, estimate_tokens
    from abc_harness.agent.loop import TOOLS, system_prompt
    from abc_harness.execution.trace import read_trace

    secrets = Secrets.load(ROOT / ".env")
    if not secrets.has("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set in .env")
    question = "In SimBlock, does a 30 s block interval produce more orphans than 600 s with 300 nodes?"
    start = estimate_tokens(system_prompt()) + estimate_tokens(TOOLS) + estimate_tokens(question)
    result = run_agent_task(
        question,
        AnthropicModel(secrets.get("ANTHROPIC_API_KEY")),
        FakeRunner(),
        lambda q: "Use your defaults.",
        lambda plan: ("reject", "live test: stop before running"),
        runs_root=tmp_path / "runs",
        budget=Budget(llm_call_limit=15),
        redact=secrets.redact,
        limits=ContextLimits(soft_limit=start + 500),
    )
    events = read_trace(result.artifact_dir / "trace.jsonl")
    compactions = [e for e in events if e["event"] == "compaction"]
    assert compactions and compactions[0]["summary"].strip()
    assert result.status == "rejected", result.stop_reason
    calls = [e for e in events if e["event"] == "model_call"]
    print(json.dumps([{"window": c["window"], **c["usage"]} for c in calls]))
    print("SUMMARY:", compactions[0]["summary"])


BLOCKSIM_QUESTION = (
    "When block propagation takes 30 seconds on average, does a miner with 40% of the hash power still mine "
    "40% of the main-chain blocks?"
)
SELECTION_CASES = [
    ("How does the time for a block to reach 90% of nodes change between a 300-node and a 600-node network?",
     "simblock", "BS-"),
    (BLOCKSIM_QUESTION, "blocksim", "SB-"),
]


@pytest.mark.parametrize(("question", "expected", "other_card"), SELECTION_CASES)
def test_real_model_chooses_the_simulator_that_fits(tmp_path, question, expected, other_card):
    secrets = Secrets.load(ROOT / ".env")
    if not secrets.has("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set in .env")
    reviewed = []

    def reject_after_review(plan):
        reviewed.append(plan)
        return "reject", "live test: stop before running"

    result = run_agent_task(question, AnthropicModel(secrets.get("ANTHROPIC_API_KEY")), FakeRunner(),
                            lambda q: "Use your defaults.", reject_after_review, runs_root=tmp_path / "runs",
                            budget=Budget(llm_call_limit=15), redact=secrets.redact)  # fmt: skip
    assert result.status == "rejected", result.stop_reason
    plan = reviewed[0]
    print(f"\n[{expected}] RATIONALE: {plan.data['rationale']}")
    assert plan.simulator == expected
    assert other_card in plan.data["rationale"], "the rationale must cite the other simulator's card"


def test_real_model_plans_code_for_a_missing_capability(tmp_path):
    """Selfish mining is in neither simulator (SB-N1, BS-N2). Since M5 the agent proposes permitted edits and a
    validation check instead of giving up; the review rejects the plan, so no code is written."""
    secrets = Secrets.load(ROOT / ".env")
    if not secrets.has("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set in .env")
    from abc_harness.execution.runner import DockerRunner, RunnerError
    from abc_harness.literature import HttpFetcher, Literature
    from abc_harness.simulators.blocksim import BlockSim

    runner = DockerRunner()  # for the real source; the review rejects, so no simulation or command runs
    try:
        runner.image_info(BlockSim.image_tag)
    except (RunnerError, FileNotFoundError):
        pytest.skip("execution images missing; run `uv run abc-harness image build`")
    reviewed = []
    result = run_agent_task(
        "How much more than its fair share of rewards does a selfish miner with 33% of the hash power earn?",
        AnthropicModel(secrets.get("ANTHROPIC_API_KEY")), runner, lambda q: "Use your defaults.",
        lambda plan: reviewed.append(plan) or ("reject", "live test"), runs_root=tmp_path / "runs",
        budget=Budget(llm_call_limit=40), redact=secrets.redact, literature=Literature(HttpFetcher()),
    )  # fmt: skip
    assert result.status == "rejected", result.stop_reason
    plan = reviewed[0]
    print(f"\n[edits] {plan.render()}")
    assert plan.permitted_paths, "the plan must name the files it will change"
    assert plan.validation is not None
    assert "SB-N1" in plan.data["rationale"] or "BS-N2" in plan.data["rationale"]


def test_real_model_finds_and_cites_a_source(tmp_path):
    """Acceptance row "Literature retrieval": a question that needs a reference, with no paper supplied."""
    from abc_harness.literature import HttpFetcher, Library, Literature

    secrets = Secrets.load(ROOT / ".env")
    if not secrets.has("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set in .env")
    s2_key = secrets.get("SEMANTIC_SCHOLAR_API_KEY") if secrets.has("SEMANTIC_SCHOLAR_API_KEY") else None
    reviewed = []
    result = run_agent_task(
        "In BlockSim, compare the stale block rate at the average Bitcoin block propagation delay reported in "
        "published measurements of the Bitcoin network with a delay ten times larger.",
        AnthropicModel(secrets.get("ANTHROPIC_API_KEY")), FakeRunner(), lambda q: "Use your defaults.",
        lambda plan: reviewed.append(plan) or ("reject", "live test: stop before running"),
        runs_root=tmp_path / "runs", budget=Budget(llm_call_limit=30), redact=secrets.redact,
        literature=Literature(HttpFetcher(), s2_key),
    )  # fmt: skip
    assert result.status == "rejected", result.stop_reason
    citations = reviewed[0].data.get("citations") or []
    print("\n[literature] " + "\n".join(f"{c['paper']} -> {c['supports']}: {c['quote']}" for c in citations))
    assert citations, "the plan must cite at least one source"
    library = Library.load(result.artifact_dir)
    for c in citations:
        assert library.locate(c["paper"], c["quote"]) is not None


def test_real_model_reads_a_value_off_a_figure(tmp_path):
    """How far a figure reading can be trusted: Figure 1 of arXiv 2007.05614 puts the alpha = 0.45 curve at
    about 0.954 for expected horizon 10 (log x axis, gridlines every 0.01)."""
    import re

    from abc_harness.execution.trace import read_trace
    from abc_harness.literature import HttpFetcher, Literature

    secrets = Secrets.load(ROOT / ".env")
    if not secrets.has("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set in .env")
    result = run_agent_task(
        "Find the paper 'Efficient MDP Analysis for Selfish-Mining in Blockchains' (AFT 2020). In its Figure 1, "
        "what normalized revenue does the alpha = 0.45 curve show at an expected horizon of 10? Do not propose a "
        "plan. End your answer with one line 'READING: <value> ± <uncertainty>'.",
        AnthropicModel(secrets.get("ANTHROPIC_API_KEY")), FakeRunner(), lambda q: "Use your defaults.",
        lambda plan: ("reject", "live test"), runs_root=tmp_path / "runs", budget=Budget(llm_call_limit=20),
        redact=secrets.redact, literature=Literature(HttpFetcher()),
    )  # fmt: skip
    events = read_trace(result.artifact_dir / "trace.jsonl")
    assert any(e.get("tool") == "view_figure" and e.get("images") for e in events), "the model must view the figure"
    report = (result.artifact_dir / "report.md").read_text()
    match = re.search(r"READING:\s*([0-9.]+)\s*±\s*([0-9.]+)", report)
    print(f"\n[figure] {match.group(0) if match else report[-500:]}")
    assert match, "the answer must end with a READING line"
    value, uncertainty = float(match.group(1)), float(match.group(2))
    assert abs(value - 0.954) <= 0.01
    assert value - uncertainty <= 0.954 <= value + uncertainty


@pytest.mark.parametrize("name", ["deepseek-flash", "deepseek-v4-pro", "kimi-k3.1-pro", "kimi-k3.1-pro-highspeed",
                                  "kimi-k3"])
def test_compatible_provider_answers_a_tool_call_and_reports_usage(name):
    """A non-Anthropic provider takes the harness's request as sent (thinking, effort, cache_control), calls a
    tool, and continues after the tool result with its own thinking blocks passed back unchanged."""
    from abc_harness.agent.model import MODELS, make_model
    from abc_harness.tools import TOOLS

    key_name = MODELS[name].provider.key_name
    secrets = Secrets.load(ROOT / ".env", names=(key_name,))
    if not secrets.has(key_name):
        pytest.skip(f"{key_name} is not set in .env")
    model = make_model(name, "high", lambda key: secrets.get(key) if secrets.has(key) else None)
    system = "You plan blockchain simulations. Use the tools."
    messages = [{"role": "user", "content": "Read the SimBlock capability card, then say in one sentence what "
                                            "SimBlock simulates."}]  # fmt: skip
    turn = model.create(system, messages, TOOLS, max_tokens=4000, timeout_seconds=120)
    assert turn.stop_reason == "tool_use", (turn.stop_reason, turn.text())
    use = turn.tool_uses()[0]
    assert use["name"] == "describe_simulator"
    assert turn.usage.get("input_tokens", 0) + turn.usage.get("cache_read_input_tokens", 0) > 0
    assert turn.usage.get("output_tokens", 0) > 0
    messages += [{"role": "assistant", "content": turn.content},
                 {"role": "user", "content": [{"type": "tool_result", "tool_use_id": use["id"],
                                               "content": "SimBlock simulates block propagation in a Bitcoin-like "
                                                          "peer-to-peer network."}]}]  # fmt: skip
    after = model.create(system, messages, TOOLS, max_tokens=4000, timeout_seconds=120)
    assert after.stop_reason == "end_turn" and "propagation" in after.text().lower(), (after.stop_reason, after.text())
