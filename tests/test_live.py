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


def test_real_model_names_the_missing_capability(tmp_path):
    secrets = Secrets.load(ROOT / ".env")
    if not secrets.has("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set in .env")
    reviewed = []
    result = run_agent_task(
        "How much more than its fair share of rewards does a selfish miner with 33% of the hash power earn?",
        AnthropicModel(secrets.get("ANTHROPIC_API_KEY")), FakeRunner(), lambda q: "Use your defaults.",
        lambda plan: reviewed.append(plan) or ("reject", "live test"), runs_root=tmp_path / "runs",
        budget=Budget(llm_call_limit=15), redact=secrets.redact,
    )  # fmt: skip
    report = (result.artifact_dir / "report.md").read_text()
    print("\n[neither] " + report)
    assert result.status == "not_executed", result.stop_reason
    assert reviewed == []
    assert "SB-N1" in report and "BS-N2" in report
