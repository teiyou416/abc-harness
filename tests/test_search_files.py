"""search_files: line search and file listing, limited to the paths read_file may read."""

from __future__ import annotations

import pytest
from doubles.fake_runner import FakeRunner
from doubles.scripted_model import ScriptedModel, text_turn, tool_turn

from abc_harness.agent.loop import run_agent_task
from abc_harness.execution.task import Task
from abc_harness.tools import HANDLERS, ToolContext, ToolError

CONFIG = "source/simblock/main/java/simblock/settings/SimulationConfiguration.java"


@pytest.fixture
def ctx(tmp_path):
    task = Task(FakeRunner(), tmp_path / "runs")
    return ToolContext(task, ask=lambda q: "", review=lambda plan: ("approve", ""))


def search(ctx, **args):
    return HANDLERS["search_files"](ctx, args)


def test_matching_lines_come_back_as_readable_paths_with_line_numbers(ctx):
    result = search(ctx, path="source/simblock/", pattern=r"NUM_OF_NODES\s*=", glob="*.java")
    lines = result.splitlines()
    assert lines[0].startswith("[2 matching lines in 1 files under source/simblock/")
    assert lines[1] == f"{CONFIG}:6: public static final int NUM_OF_NODES = 300; // 600;//800;//6000;"
    # The path and line work with read_file as they are.
    path, line = lines[1].split(":")[:2]
    read = HANDLERS["read_file"](ctx, {"path": path, "offset": int(line), "limit": 1})
    assert "NUM_OF_NODES = 300" in read


def test_without_a_pattern_it_lists_files_by_name(ctx):
    result = search(ctx, path="source/simblock", glob="*.java")
    assert result.splitlines()[1:] == [CONFIG, "source/simblock/main/java/simblock/simulator/Main.java"]
    assert "No file matches." in search(ctx, path="source/simblock", glob="*.py")


def test_case_and_result_limits(ctx):
    assert "No line matches." in search(ctx, path="source/simblock", pattern="num_of_nodes")
    assert "[2 matching lines" in search(ctx, path="source/simblock", pattern="num_of_nodes", ignore_case=True)
    capped = search(ctx, path="source/simblock", pattern=".", max_results=3)
    assert "showing the first 3" in capped and len(capped.splitlines()) == 4


def test_task_directory_and_binary_files(ctx):
    papers = ctx.task.artifact_dir / "papers"
    papers.mkdir()
    (papers / "p.txt").write_text("intro\nThe stale rate was 0.41% at 12.6 s.\n")
    (papers / "fig.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0stale rate")
    result = search(ctx, path="task/papers/", pattern="stale rate")
    assert result.splitlines()[1:] == ["task/papers/p.txt:2: The stale rate was 0.41% at 12.6 s."]


@pytest.mark.parametrize(("args", "message"), [
    ({"path": "/etc", "pattern": "root"}, "path must start with"),
    ({"path": "task/../../..", "pattern": "x"}, "outside task/"),
    ({"path": "source/other/", "pattern": "x"}, "one folder per simulator"),
    ({"path": "source/simblock", "pattern": "("}, "invalid regular expression"),
    ({"path": "task/missing", "pattern": "x"}, "nothing at task/missing"),
    ({"path": "source/simblock", "pattern": "x", "max_results": "many"}, "whole number"),
])  # fmt: skip
def test_refused_searches(ctx, args, message):
    with pytest.raises(ToolError, match=message):
        search(ctx, **args)


def test_symlinks_out_of_a_root_are_not_followed(ctx, tmp_path):
    secret = tmp_path / "outside.txt"
    secret.write_text("TOP SECRET\n")
    (ctx.task.artifact_dir / "link.txt").symlink_to(secret)
    assert "No line matches." in search(ctx, path="task/", pattern="TOP SECRET")


def test_the_agent_can_search_and_the_call_is_traced(tmp_path):
    model = ScriptedModel([
        tool_turn("search_files", {"path": "source/simblock/", "pattern": "INTERVAL"}),
        text_turn("Found it."),
    ])  # fmt: skip
    run_agent_task("Where is the block interval set?", model, FakeRunner(), lambda q: "", lambda p: ("approve", ""),
                   runs_root=tmp_path / "runs")  # fmt: skip
    result = model.calls[1][-1]["content"][0]["content"]
    assert f"{CONFIG}:8: public static final long INTERVAL" in result
