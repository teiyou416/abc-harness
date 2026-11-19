"""Calls the real Claude API. Run with `make test-live`; needs ANTHROPIC_API_KEY in .env.

The researcher's side rejects the first plan, so no simulator runs and the cost
stays at a few model calls. The test checks that a real model drafts a plan the
harness accepts and that the key never reaches the trace.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from doubles.fake_runner import FakeRunner

from abc_harness.agent import run_agent_task
from abc_harness.limits import Budget
from abc_harness.model import AnthropicModel
from abc_harness.secrets import Secrets

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

    from abc_harness.agent import TOOLS, system_prompt
    from abc_harness.context import ContextLimits, estimate_tokens
    from abc_harness.trace import read_trace

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
