from __future__ import annotations

import json
from datetime import datetime

from abc_harness.agent.session import ChatSession
from abc_harness.execution.cleanup import REMOVED_NOTE, apply_cleanup, plan_cleanup
from abc_harness.interfaces import cli
from abc_harness.interfaces.chat import run_chat

NOW = datetime(2026, 11, 22, 12, 0)


def make_task(root, task_id, status, scratch_bytes=0, ended=True):
    task = root / task_id
    (task / "raw").mkdir(parents=True)
    (task / "raw" / "out.csv").write_text("evidence")
    (task / "workspace" / "edited").mkdir(parents=True)
    scratch = task / "workspace" / "scratch"
    scratch.mkdir()
    if scratch_bytes:
        (scratch / "build").mkdir()
        (scratch / "build" / "Main.class").write_bytes(b"x" * scratch_bytes)
    if ended:
        (task / "manifest.json").write_text(json.dumps({"status": status}))
    return task


def test_cleanup_lists_sandbox_files_and_old_unrun_tasks_and_keeps_evidence(tmp_path):
    runs = tmp_path / "runs"
    done = make_task(runs, "20261120-100000-aaaaaa", "completed", scratch_bytes=1000)
    running = make_task(runs, "20261122-110000-bbbbbb", "", scratch_bytes=500, ended=False)
    old_reject = make_task(runs, "20261001-100000-cccccc", "rejected")
    new_reject = make_task(runs, "20261121-100000-dddddd", "rejected")
    old_done = make_task(runs, "20261001-100000-eeeeee", "completed")
    old_reply = make_task(runs / "sessions" / "s1" / "replies", "20261001-100000-ffffff", "not_executed")

    assert [(r.path, r.what) for r in plan_cleanup(runs, now=NOW)] == [(done / "workspace" / "scratch", "scratch")]

    removals = plan_cleanup(runs, older_than_days=30, now=NOW)
    assert {(r.path, r.what) for r in removals} == {
        (done / "workspace" / "scratch", "scratch"), (old_reject, "task"), (old_reply, "task")}
    assert next(r.size for r in removals if r.what == "scratch") == 1000

    assert apply_cleanup(removals, now=NOW) >= 1000
    assert not old_reject.exists() and not old_reply.exists()
    assert new_reject.exists() and old_done.exists() and (done / "raw" / "out.csv").exists()
    assert [p.name for p in (done / "workspace" / "scratch").iterdir()] == [REMOVED_NOTE]
    assert "2026-11-22" in (done / "workspace" / "scratch" / REMOVED_NOTE).read_text()
    assert (running / "workspace" / "scratch" / "build").exists()  # a running task is never touched
    assert plan_cleanup(runs, older_than_days=30, now=NOW) == []  # the note alone is not worth removing


def test_clean_command_only_lists_without_yes(tmp_path, capsys):
    runs = tmp_path / "runs"
    task = make_task(runs, "20261120-100000-aaaaaa", "completed", scratch_bytes=2048)
    assert cli.main(["clean", "--runs-dir", str(runs)]) == 0
    out = capsys.readouterr().out
    assert "sandbox files in 20261120-100000-aaaaaa/workspace/scratch (completed)" in out and "--yes" in out
    assert (task / "workspace" / "scratch" / "build").exists()

    assert cli.main(["clean", "--runs-dir", str(runs), "--yes"]) == 0
    assert "Removed 2.0 KB." in capsys.readouterr().out
    assert not (task / "workspace" / "scratch" / "build").exists()


def test_chat_clean_asks_first_and_defaults_to_no(tmp_path):
    runs = tmp_path / "runs"
    task = make_task(runs, "20261120-100000-aaaaaa", "completed", scratch_bytes=100)
    answers = iter(["/clean", "", "/clean abc", "/clean", "y", "/clean", "/quit"])
    out = []

    def turn(_session, _text):
        raise AssertionError("no request was sent")

    run_chat(lambda: ChatSession(runs), turn, lambda _p: next(answers), out.append)
    assert "Nothing was removed." in out and "! /clean takes a number of days, not 'abc'" in out
    assert "Removed 100 B." in out and f"Nothing to remove in {runs}." in out
    assert not (task / "workspace" / "scratch" / "build").exists()


def test_sizes_are_shown_in_the_largest_fitting_unit():
    from abc_harness.execution.cleanup import human_size

    assert [human_size(n) for n in (512, 2048, 5 * 1024**2, 3 * 1024**3, 2048 * 1024**3)] == [
        "512 B", "2.0 KB", "5.0 MB", "3.0 GB", "2048.0 GB"]  # fmt: skip
