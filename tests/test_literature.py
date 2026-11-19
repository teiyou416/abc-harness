"""Literature search, full text, citation checks, and the agent flow, against recorded HTTP responses."""

from __future__ import annotations

import json

import pytest
from doubles.fake_runner import FakeClock, FakeRunner
from doubles.recorded_http import RECORDED, FakeTime, RecordedFetcher, recorded_literature
from doubles.scripted_model import ScriptedModel, last_tool_result, run_last_proposed, text_turn, tool_turn

from abc_harness.agent.loop import run_agent_task
from abc_harness.execution.limits import Budget
from abc_harness.execution.task import run_task
from abc_harness.execution.trace import read_trace
from abc_harness.literature import Library
from abc_harness.literature.fulltext import html_to_lines, outline
from abc_harness.literature.http import FetchError, PoliteClient
from abc_harness.planning.plan import PlanError, validate_plan

ABSTRACT_QUOTE = "Sufficiently large miners can perform selfish mining"
FULL_TEXT_QUOTE = "Eyal and Sirer (Eyal and Sirer, 2013) were the first to show that the Bitcoin protocol is not incentive compatible."
S2_KEY = "s2-test-key-0123456789"


def library(tmp_path, s2_key=None, **failures):
    literature, fetcher = recorded_literature(s2_key, **failures)
    return Library(tmp_path, literature), fetcher


def test_first_round_searches_only_the_configured_venues(tmp_path):
    lib, fetcher = library(tmp_path)
    papers, errors = lib.search("selfish mining", broaden=False, limit=3, time_left=60)
    assert errors == []
    assert papers[0].id == "arxiv:2007.05614"
    assert {p.venue for p in papers} <= {"ACM Conference on Advances in Financial Technologies (AFT)",
                                         "IEEE International Conference on Blockchain and Cryptocurrency (ICBC)"}  # fmt: skip
    assert "primary_location.source.id" in fetcher.requests[0][0]
    assert papers[0].abstract.startswith("A proof of work (PoW) blockchain protocol")
    saved = json.loads((tmp_path / "sources.json").read_text())
    assert saved["searches"][0]["venues"] == ["FC", "AFT", "ICBC"]
    assert len(saved["papers"]) == 3


def test_broadening_drops_the_venue_filter(tmp_path):
    lib, fetcher = library(tmp_path)
    papers, _ = lib.search("bitcoin block propagation delay", broaden=True, limit=3, time_left=60)
    assert "filter=" not in fetcher.requests[0][0]
    assert any("Information propagation in the Bitcoin network" in p.title for p in papers)


def test_semantic_scholar_gets_the_key_and_nothing_else_does(tmp_path):
    lib, fetcher = library(tmp_path, s2_key=S2_KEY)
    papers, _ = lib.search("selfish mining", broaden=False, limit=3, time_left=60)
    assert papers[0].id == "arxiv:1311.0243" and papers[0].venue == "Financial Cryptography"
    assert fetcher.requests[0][1] == {"x-api-key": S2_KEY}
    lib.search("bitcoin block propagation delay", broaden=True, limit=3, time_left=60)
    assert all("x-api-key" not in headers for url, headers in fetcher.requests if "openalex" in url)
    assert S2_KEY not in (tmp_path / "sources.json").read_text()


def test_full_text_is_saved_once_and_paged_by_outline(tmp_path):
    lib, fetcher = library(tmp_path)
    lib.search("selfish mining", broaden=False, limit=3, time_left=60)
    rel, lines = lib.read("arxiv:2007.05614", time_left=60)
    assert rel == "papers/2007.05614.txt" and (tmp_path / rel).exists()
    assert lines[0] == "# Source: https://arxiv.org/html/2007.05614"
    assert "line 16: ## 1. Introduction" in outline(lines)
    requests = len(fetcher.requests)
    lib.read("arxiv:2007.05614", time_left=60)
    assert len(fetcher.requests) == requests


def test_full_text_falls_back_to_ar5iv(tmp_path):
    lib, fetcher = library(tmp_path)
    lib.search("selfish mining", broaden=False, limit=3, time_left=60)
    RECORDED["https://ar5iv.labs.arxiv.org/html/2007.05614"] = RECORDED["https://arxiv.org/html/2007.05614"]
    try:
        fetcher.failures["https://arxiv.org/html/2007.05614"] = [404]
        _, lines = lib.read("arxiv:2007.05614", time_left=60)
    finally:
        del RECORDED["https://ar5iv.labs.arxiv.org/html/2007.05614"]
    assert lines[0] == "# Source: https://ar5iv.labs.arxiv.org/html/2007.05614"


def test_html_keeps_headings_and_math_source():
    html = (RecordedFetcher().get("https://arxiv.org/html/2007.05614", {}, 1)).decode()
    lines = html_to_lines(html)
    assert "# Efficient MDP Analysis for Selfish-Mining in Blockchains" in lines
    assert any("$s_{t}\\in\\mathcal{S}$" in line for line in lines)
    assert not any("<script" in line or "function(" in line for line in lines)


def test_quotes_are_located_verbatim_and_nowhere_else(tmp_path):
    lib, _ = library(tmp_path)
    lib.search("selfish mining", broaden=False, limit=3, time_left=60)
    assert lib.locate("arxiv:2007.05614", ABSTRACT_QUOTE) == "abstract"
    assert lib.locate("arxiv:2007.05614", FULL_TEXT_QUOTE) is None  # full text not read yet
    lib.read("arxiv:2007.05614", time_left=60)
    assert lib.locate("arxiv:2007.05614", FULL_TEXT_QUOTE.upper().replace(" ", "  ")) == "papers/2007.05614.txt line 27"
    assert lib.locate("arxiv:2007.05614", "selfish mining") is None  # too short to mean anything
    assert lib.locate("arxiv:2007.05614", "Sufficiently large miners can always double their reward") is None
    assert lib.locate("arxiv:9999.99999", ABSTRACT_QUOTE) is None
    assert Library.load(tmp_path).locate("arxiv:2007.05614", FULL_TEXT_QUOTE) is not None


def test_polite_client_waits_retries_and_respects_the_deadline():
    time = FakeTime()
    url = next(u for u in RECORDED if "openalex" in u)
    fetcher = RecordedFetcher(failures={url: [429, 503]})
    client = PoliteClient(fetcher, clock=time.clock, sleep=time.sleep)
    assert client.get(url, time_left=60)
    assert len(fetcher.requests) == 3 and time.sleeps == [2.0, 4.0]
    client.get(url, time_left=60)
    assert time.sleeps[-1] == pytest.approx(0.2)  # minimum interval between requests to one host
    with pytest.raises(FetchError, match="404"):
        client.get("https://api.openalex.org/works?search=unrecorded", time_left=60)
    fetcher.failures[url] = [429, 429, 429]
    with pytest.raises(FetchError, match="exceed the task's active time"):
        client.get(url, time_left=3)


@pytest.mark.parametrize("citation", [
    {"paper": "arxiv:1", "supports": "x"},
    {"paper": "arxiv:1", "supports": "", "quote": "q"},
    {"paper": "arxiv:1", "supports": "x", "quote": "q" * 601},
])  # fmt: skip
def test_malformed_citations_are_refused(citation, write_plan):
    from abc_harness.planning.plan import load_plan

    with pytest.raises(PlanError, match="citation"):
        validate_plan({**load_plan(write_plan()).data, "citations": [citation]})


def blocksim_plan(**extra):
    return {
        "title": "Delay and stale rate", "question": "q", "simulator": "blocksim",
        "rationale": "BS-M2 models delay; SimBlock lacks per-miner hash power (SB-N3).", "seeds": [1, 2],
        "metrics": ["stale_rate"], "run_timeout_seconds": 30,
        "baseline": {"simTime": 86400, "HASH_POWERS": [50, 20, 30]},
        "configurations": [{"name": "base"}, {"name": "slow", "params": {"Bdelay": 60}}], **extra,
    }  # fmt: skip


def run_agent(model, tmp_path, literature=None, review=None):
    review = review or (lambda plan: ("approve", ""))
    return run_agent_task("Does propagation delay change the stale rate?", model, FakeRunner(), lambda q: "", review,
                          runs_root=tmp_path / "runs", literature=literature)  # fmt: skip


def test_agent_searches_reads_and_cites_and_the_report_shows_where(tmp_path):
    literature, _ = recorded_literature()
    citation = {"paper": "arxiv:2007.05614", "supports": "studying incentives under honest mining",
                "quote": FULL_TEXT_QUOTE}  # fmt: skip
    model = ScriptedModel([
        tool_turn("search_papers", {"query": "selfish mining", "limit": 3}),
        tool_turn("read_paper", {"paper": "arxiv:2007.05614"}),
        tool_turn("read_file", {"path": "task/papers/2007.05614.txt", "offset": 26, "limit": 2}),
        tool_turn("propose_plan", blocksim_plan(citations=[citation])),
        run_last_proposed,
        text_turn("Done; relied on Efficient MDP Analysis for Selfish-Mining in Blockchains."),
    ])  # fmt: skip
    result = run_agent(model, tmp_path, literature)
    assert result.status == "completed", result.stop_reason
    assert "Outline:" in model.calls[2][-1]["content"][0]["content"]
    report = (result.artifact_dir / "report.md").read_text()
    assert "## Sources" in report and "quote found in papers/2007.05614.txt line 27" in report
    assert (result.artifact_dir / "papers" / "2007.05614.txt").exists()
    plan = json.loads((result.artifact_dir / "plan.json").read_text())
    assert plan["citations"] == [citation]
    manifest = json.loads((result.artifact_dir / "manifest.json").read_text())
    assert manifest["literature_services"] == ["openalex", "arxiv_html"]


@pytest.mark.parametrize(("paper", "quote", "problem"), [
    ("arxiv:1311.0243", ABSTRACT_QUOTE, "was not returned by search_papers"),
    ("arxiv:2007.05614", "Selfish mining always pays off for any miner with more than 10% of the power.", "verbatim"),
    ("arxiv:2007.05614", FULL_TEXT_QUOTE, "read_paper first"),
])  # fmt: skip
def test_citations_the_harness_cannot_find_are_refused(tmp_path, paper, quote, problem):
    literature, _ = recorded_literature()
    seen = []
    model = ScriptedModel([
        tool_turn("search_papers", {"query": "selfish mining", "limit": 3}),
        tool_turn("propose_plan", blocksim_plan(citations=[{"paper": paper, "supports": "x", "quote": quote}])),
        lambda messages: text_turn(last_tool_result(messages)["content"]),
    ])  # fmt: skip
    result = run_agent(model, tmp_path, literature, review=lambda plan: seen.append(plan) or ("approve", ""))
    assert result.status == "not_executed" and seen == []
    assert problem in model.calls[2][-1]["content"][0]["content"]


def test_without_literature_the_tools_refuse(tmp_path):
    model = ScriptedModel([
        tool_turn("search_papers", {"query": "selfish mining"}),
        lambda messages: text_turn(last_tool_result(messages)["content"]),
    ])  # fmt: skip
    run_agent(model, tmp_path)
    assert "not configured" in model.calls[1][-1]["content"][0]["content"]


def test_search_with_no_time_left_stops_the_task(tmp_path):
    literature, fetcher = recorded_literature()
    clock = FakeClock()
    model = ScriptedModel([tool_turn("search_papers", {"query": "selfish mining", "limit": 3})], clock=clock,
                          seconds_per_call=10)  # fmt: skip
    result = run_agent_task("q", model, FakeRunner(), lambda q: "", lambda p: ("approve", ""),
                            runs_root=tmp_path / "runs", budget=Budget(time_limit_seconds=10, clock=clock),
                            literature=literature)  # fmt: skip
    assert result.status == "stopped_by_limit" and fetcher.requests == []


def test_plan_file_citations_are_reported_as_not_checked(tmp_path):
    plan = blocksim_plan(citations=[{"paper": "arxiv:1311.0243", "supports": "x", "quote": ABSTRACT_QUOTE}])
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan))
    result = run_task(path, FakeRunner(), lambda p: ("approve", ""), runs_root=tmp_path / "runs")
    assert result.status == "completed"
    assert "not checked: this citation came with the plan file" in (result.artifact_dir / "report.md").read_text()


def test_search_requests_and_results_are_traced_without_the_key(tmp_path):
    literature, _ = recorded_literature(s2_key=S2_KEY)
    model = ScriptedModel([tool_turn("search_papers", {"query": "selfish mining", "limit": 3}), text_turn("ok")])
    result = run_agent(model, tmp_path, literature)
    events = read_trace(result.artifact_dir / "trace.jsonl")
    call = next(e for e in events if e["event"] == "tool_call")
    assert call["tool"] == "search_papers" and "arxiv:1311.0243" in call["result"]
    assert S2_KEY not in (result.artifact_dir / "trace.jsonl").read_text()
