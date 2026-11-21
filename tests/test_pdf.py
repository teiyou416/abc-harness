"""PDF full text: MinerU output parsing, supplied papers, the arXiv PDF fallback, the parse cache, and limits.

The parser itself is replaced by FakeRunner.convert_pdf, which copies a trimmed recorded MinerU output
(tests/fixtures/pdf/). test_docker.py runs the real parser image.
"""

from __future__ import annotations

import json

import pytest
from doubles.fake_runner import FakeClock, FakeRunner
from doubles.recorded_http import RECORDED, recorded_literature
from doubles.scripted_model import ScriptedModel, last_tool_result, run_last_proposed, text_turn, tool_turn
from test_literature import blocksim_plan

from abc_harness.agent.loop import run_agent_task
from abc_harness.execution.limits import Budget
from abc_harness.execution.task import Task
from abc_harness.execution.trace import read_trace
from abc_harness.interfaces import cli
from abc_harness.literature import Library
from abc_harness.literature.http import FetchError
from abc_harness.literature.pdf import NOTE, PARSER_IMAGE, TABLE_WARNING, PdfError, parse_structured

FIXTURE = "tests/fixtures/pdf"
PAPER = "local:my-paper"
TEXT_QUOTE = "PTO reproduces the results of OSM"
TABLE_QUOTE = "| 0 375 | 0 426 00 | 0 426 00 |"
TABLE_READING = {"paper": PAPER, "supports": "revenue at alpha 0.35", "figure": "Table 1",
                 "reading": "0.37077 ± 0.00001 for alpha 0.35 (PTO column)"}  # fmt: skip


@pytest.fixture
def structured(request):
    from pathlib import Path

    root = Path(request.config.rootpath) / FIXTURE / "2007.05614" / "structured_content.json"
    return json.loads(root.read_text(encoding="utf-8"))


@pytest.fixture
def supplied_pdf(tmp_path):
    path = tmp_path / "My Paper.pdf"
    path.write_bytes(b"%PDF-1.4\nnot a real document; FakeRunner ignores it\n")
    return path


def run_agent(model, tmp_path, papers, runner=None, literature=None, review=None, clock=None):
    runner = runner or FakeRunner(clock=clock)
    budget = Budget(clock=clock) if clock else None
    return run_agent_task("Reproduce Table 1.", model, runner, lambda q: "", review or (lambda plan: ("approve", "")),
                          runs_root=tmp_path / "runs", literature=literature, papers=papers, budget=budget)  # fmt: skip


# ----- MinerU output -----


def test_structured_output_becomes_lines_figures_and_tables(structured):
    parsed = parse_structured(structured, "papers/p/pdf")
    assert parsed.title == "Efficient MDP Analysis for Selfish-Mining in Blockchains"
    assert parsed.abstract.startswith("A proof of work (PoW) blockchain protocol")
    assert parsed.lines[0] == "# Efficient MDP Analysis for Selfish-Mining in Blockchains"
    assert "## 1 INTRODUCTION" in parsed.lines
    assert not any("arXiv:2007.05614v2" in line for line in parsed.lines)  # page furniture is dropped
    # A paragraph continued in the next column is one line, so a quote across the break matches.
    assert any("including Bitcoin [15] and Ethereum [2]. The operators" in line for line in parsed.lines)
    labels = [f.label for f in parsed.figures]
    assert labels == ["Table 1", "Figure 1", "Figure 2"]
    table = parsed.figures[0]
    assert table.images == ["papers/p/pdf/images/page_7_table_15.jpg"]
    assert parsed.lines[table.line - 1].startswith("Table 1: Comparison between PTO")
    assert parsed.lines[table.line] == TABLE_WARNING
    assert parsed.lines[table.line + 1].startswith("| Power (α)")


def test_unsafe_image_paths_are_dropped_and_panels_merge():
    blocks = [
        {"type": "chart", "image_source": "../../outside.jpg", "captions": [{"content": "Figure 1: Escapes."}]},
        {"type": "image", "image_source": "images/a.jpg", "captions": [{"content": "Figure 2: Left."}]},
        {"type": "image", "image_source": "images/b.jpg", "captions": [{"content": "Figure 2: Right."}]},
        {"type": "equation", "content": "x = 1"},
    ]  # fmt: skip
    parsed = parse_structured({"pages": [{"page_idx": 0, "blocks": blocks}]}, "out")
    assert [(f.label, f.images) for f in parsed.figures] == [("Figure 2", ["out/images/a.jpg", "out/images/b.jpg"])]
    assert "$$ x = 1 $$" in parsed.lines


# ----- supplied PDFs -----


def test_supplied_pdf_is_parsed_before_the_agent_starts_and_can_be_cited(tmp_path, supplied_pdf):
    clock = FakeClock()
    citations = [{"paper": PAPER, "supports": "PTO is exact", "quote": TEXT_QUOTE}, TABLE_READING]
    model = ScriptedModel([
        tool_turn("read_paper", {"paper": PAPER}),
        tool_turn("view_figure", {"paper": PAPER, "figure": "Table 1"}),
        tool_turn("propose_plan", blocksim_plan(citations=citations)),
        run_last_proposed,
        text_turn("Done."),
    ])  # fmt: skip
    result = run_agent(model, tmp_path, [supplied_pdf], clock=clock)
    assert result.status == "completed", result.stop_reason
    first = model.calls[0][0]["content"]
    assert first.startswith("Reproduce Table 1.") and f"`{PAPER}`: Efficient MDP Analysis" in first
    opened = model.calls[1][-1]["content"][0]["content"]
    assert NOTE in opened and "Figures and tables (view one with view_figure" in opened
    assert "- Table 1 (at line" in opened
    shown = model.calls[2][-1]["content"][0]["content"]
    assert [b["type"] for b in shown] == ["text", "image"] and shown[1]["source"]["media_type"] == "image/jpeg"

    task_dir = result.artifact_dir
    assert (task_dir / "papers" / "local-my-paper.pdf").read_bytes() == supplied_pdf.read_bytes()
    saved = json.loads((task_dir / "literature.json").read_text())
    assert saved["sources"][PAPER]["kind"] == "pdf" and saved["sources"][PAPER]["file"] == "My Paper.pdf"
    assert "mineru_pdf" in saved["services"]
    manifest = json.loads((task_dir / "manifest.json").read_text())
    assert manifest["supplied_papers"] == ["My Paper.pdf"]
    assert manifest["pdf_parse_seconds"] == 120.0 and manifest["active_seconds"] < 120
    assert manifest["pdf_parses"][0]["cached"] is False
    events = [e["event"] for e in read_trace(task_dir / "trace.jsonl")]
    assert events.index("pdf_parse_finished") < events.index("model_call")
    report = (task_dir / "report.md").read_text()
    assert "PDF parsing: 1 PDF(s); 120.0s, not counted in active runtime" in report
    assert "machine-recognized from [the PDF](papers/local-my-paper.pdf) by MinerU" in report
    assert "[image](papers/local-my-paper/pdf/images/page_7_table_15.jpg)" in report


def test_a_quote_from_a_pdf_table_is_refused(tmp_path, supplied_pdf):
    seen = []
    model = ScriptedModel([
        tool_turn("read_paper", {"paper": PAPER}),
        tool_turn("propose_plan", blocksim_plan(citations=[{"paper": PAPER, "supports": "x", "quote": TABLE_QUOTE}])),
        lambda messages: text_turn(last_tool_result(messages)["content"]),
    ])  # fmt: skip
    result = run_agent(model, tmp_path, [supplied_pdf], review=lambda plan: seen.append(plan) or ("approve", ""))
    assert result.status == "not_executed" and seen == []
    assert "comes from a table recognized from the PDF" in model.calls[2][-1]["content"][0]["content"]


@pytest.mark.parametrize(("behaviour", "reason"), [
    ("fail", "the PDF parser failed (exit code 1)"),
    ("timeout", "did not finish within 15 minutes"),
    ("garbage", "unreadable output"),
])  # fmt: skip
def test_a_supplied_pdf_that_cannot_be_parsed_ends_the_task(tmp_path, supplied_pdf, behaviour, reason):
    model = ScriptedModel([text_turn("never called")])
    result = run_agent(model, tmp_path, [supplied_pdf], runner=FakeRunner(pdf_behaviour=behaviour))
    assert result.status == "failed"
    assert "could not parse the supplied paper My Paper.pdf" in result.stop_reason and reason in result.stop_reason
    assert model.calls == []
    if behaviour != "garbage":
        assert "pdf_parse_failed" in [e["event"] for e in read_trace(result.artifact_dir / "trace.jsonl")]


def test_without_the_parser_image_a_supplied_pdf_ends_the_task(tmp_path, supplied_pdf):
    runner = FakeRunner(missing_images={PARSER_IMAGE})
    result = run_agent(ScriptedModel([text_turn("never called")]), tmp_path, [supplied_pdf], runner=runner)
    assert result.status == "failed" and "has no PDF parser" in result.stop_reason


def test_cli_checks_supplied_files_before_starting(tmp_path, capsys):
    text = tmp_path / "notes.pdf"
    text.write_text("plain text\n")
    assert cli.main(["ask", "q", "--paper", str(tmp_path / "missing.pdf"), "--runs-dir", str(tmp_path)]) == 2
    assert cli.main(["ask", "q", "--paper", str(text), "--runs-dir", str(tmp_path)]) == 2
    err = capsys.readouterr().err
    assert "no such file" in err and "not a PDF file" in err
    assert list(tmp_path.iterdir()) == [text]  # no task was created


# ----- the arXiv PDF fallback -----


def arxiv_without_html(tmp_path, monkeypatch, runner=None):
    monkeypatch.setitem(RECORDED, "https://arxiv.org/pdf/2007.05614", "../pdf/handwritten.pdf")
    literature, fetcher = recorded_literature()
    fetcher.failures["https://arxiv.org/html/2007.05614"] = [404]  # and ar5iv has no recording either
    task = Task(runner or FakeRunner(), tmp_path / "runs")
    return task, Library(task.artifact_dir, literature, task.convert_pdf)


def test_arxiv_paper_without_html_is_read_from_its_pdf(tmp_path, monkeypatch):
    task, lib = arxiv_without_html(tmp_path, monkeypatch)
    lib.search("selfish mining", broaden=False, limit=3, time_left=60)
    rel, lines = lib.read("arxiv:2007.05614", time_left=60)
    assert rel == "papers/2007.05614.txt"
    assert lines[0].startswith("# Source: https://arxiv.org/pdf/2007.05614 (no HTML on arXiv); parsed by mineru 4.2.3")
    assert lines[1] == NOTE
    source = lib.sources["arxiv:2007.05614"]
    assert source["kind"] == "pdf" and "404" in source["html_error"]
    assert (task.artifact_dir / "papers" / "2007.05614.pdf").read_bytes().startswith(b"%PDF")
    assert lib.locate("arxiv:2007.05614", TEXT_QUOTE).startswith("papers/2007.05614.txt line")
    assert lib.locate("arxiv:2007.05614", "machine-recognized from the PDF by MinerU") is None  # not the paper's words
    _, shown, _ = lib.view("arxiv:2007.05614", "Figure 1", time_left=60)
    assert shown[0][0] == "papers/2007.05614/pdf/images/page_8_chart_2.jpg"


def test_without_a_parser_a_missing_html_stays_an_error(tmp_path, monkeypatch):
    literature, fetcher = recorded_literature()
    fetcher.failures["https://arxiv.org/html/2007.05614"] = [404]
    lib = Library(tmp_path, literature)
    lib.search("selfish mining", broaden=False, limit=3, time_left=60)
    with pytest.raises(FetchError):
        lib.read("arxiv:2007.05614", time_left=60)
    assert not any("/pdf/" in url for url, _ in fetcher.requests)


# ----- cache and limits -----


def test_the_same_pdf_and_parser_image_are_parsed_once(tmp_path, supplied_pdf):
    runner = FakeRunner()
    first = run_agent(ScriptedModel([text_turn("Done.")]), tmp_path, [supplied_pdf], runner=runner)
    second = run_agent(ScriptedModel([text_turn("Done.")]), tmp_path, [supplied_pdf], runner=runner)
    assert runner.pdf_calls == ["local-my-paper.pdf"]
    manifest = json.loads((second.artifact_dir / "manifest.json").read_text())
    assert manifest["pdf_parses"][0]["cached"] is True and manifest["pdf_parses"][0]["seconds"] == 120.0
    assert "1 reused from the parse cache" in (second.artifact_dir / "report.md").read_text()
    assert (first.artifact_dir / "papers" / "local-my-paper.txt").read_text().splitlines()[2:] == \
        (second.artifact_dir / "papers" / "local-my-paper.txt").read_text().splitlines()[2:]  # fmt: skip
    runner.rebuild(PARSER_IMAGE)  # a new parser image parses again
    run_agent(ScriptedModel([text_turn("Done.")]), tmp_path, [supplied_pdf], runner=runner)
    assert len(runner.pdf_calls) == 2


def test_parse_time_does_not_count_toward_the_time_limit(tmp_path, supplied_pdf):
    clock = FakeClock()
    runner = FakeRunner(clock=clock, seconds_per_pdf=600)
    result = run_agent(ScriptedModel([text_turn("Done.")]), tmp_path, [supplied_pdf], runner=runner, clock=clock)
    assert result.status == "not_executed"  # a 10-minute parse inside a 2-hour limit leaves it untouched
    manifest = json.loads((result.artifact_dir / "manifest.json").read_text())
    assert manifest["pdf_parse_seconds"] == 600 and manifest["active_seconds"] == 0


def test_budget_excludes_parsing():
    clock = FakeClock()
    budget = Budget(time_limit_seconds=10, clock=clock)
    with budget.parsing_pdf():
        clock.advance(100)
    clock.advance(4)
    assert budget.active_seconds == 4 and budget.parsing_seconds == 100 and budget.remaining_seconds == 6


def test_parse_error_message_names_the_missing_image(tmp_path, supplied_pdf):
    task = Task(FakeRunner(missing_images={PARSER_IMAGE}), tmp_path / "runs")
    with pytest.raises(PdfError, match="abc-harness image build"):
        task.convert_pdf(supplied_pdf, tmp_path / "out")


# ----- local library -----


def run_with_library(model, tmp_path, library, runner, papers=()):
    return run_agent_task("Reproduce Table 1.", model, runner, lambda q: "", lambda plan: ("approve", ""),
                          runs_root=tmp_path / "runs", papers=list(papers), library_dir=library)  # fmt: skip


def test_the_local_library_is_listed_and_only_the_paper_read_is_parsed(tmp_path):
    library = tmp_path / "thesis"
    (library / "older").mkdir(parents=True)
    for name in ("My Paper.pdf", "older/Other Paper.pdf"):
        (library / name).write_bytes(f"%PDF-1.4\n{name}\n".encode())
    (library / "notes.txt").write_text("not a paper")
    runner = FakeRunner()
    citations = [{"paper": PAPER, "supports": "PTO is exact", "quote": TEXT_QUOTE}]
    model = ScriptedModel([
        tool_turn("read_paper", {"paper": PAPER}),
        tool_turn("propose_plan", blocksim_plan(citations=citations)),
        run_last_proposed,
        text_turn("Done."),
    ])  # fmt: skip
    result = run_with_library(model, tmp_path, library, runner)
    assert result.status == "completed", result.stop_reason  # a library paper can be cited once read
    first = model.calls[0][0]["content"]
    assert f"- `{PAPER}`: thesis/My Paper.pdf\n" in first and "`local:other-paper`: thesis/older/Other Paper.pdf" in first
    assert "notes.txt" not in first and "Before searching online, check this list" in first
    assert runner.pdf_calls == ["local-my-paper.pdf"]  # the other one was never parsed
    saved = json.loads((result.artifact_dir / "literature.json").read_text())
    assert saved["local_library"] == {PAPER: "thesis/My Paper.pdf", "local:other-paper": "thesis/older/Other Paper.pdf"}
    assert saved["papers"][0]["title"] == "Efficient MDP Analysis for Selfish-Mining in Blockchains"

    # The next task sees the parsed paper's own title and abstract, from the parse cache, without parsing again.
    model = ScriptedModel([text_turn("Done.")])
    run_with_library(model, tmp_path, library, runner)
    first = model.calls[0][0]["content"]
    assert (f"- `{PAPER}`: thesis/My Paper.pdf (Efficient MDP Analysis for Selfish-Mining in Blockchains). "
            "A proof of work (PoW) blockchain protocol") in first  # fmt: skip
    assert runner.pdf_calls == ["local-my-paper.pdf"]


def test_a_supplied_paper_is_not_listed_again_and_a_missing_library_is_ignored(tmp_path):
    library = tmp_path / "thesis"
    library.mkdir()
    (library / "My Paper.pdf").write_bytes(b"%PDF-1.4\n")
    model = ScriptedModel([text_turn("Done.")])
    run_with_library(model, tmp_path, library, FakeRunner(), papers=[library / "My Paper.pdf"])
    assert "local library" not in model.calls[0][0]["content"]
    model = ScriptedModel([text_turn("Done.")])
    run_with_library(model, tmp_path, tmp_path / "absent", FakeRunner())
    assert "local library" not in model.calls[0][0]["content"]
