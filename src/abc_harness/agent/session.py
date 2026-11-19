"""A chat session: one conversation in which every researcher request runs as its own task.

Each request gets a task of its own (artifact directory, approval, report,
limits), so the rules for one task do not change. What carries over is
written by the harness from the earlier tasks' records, as in the task-state
block: the question, the plan, the results table, the figures, and the
agent's final answer. The earlier artifact directories are readable at
`previous/<task_id>/`. `runs/sessions/<session_id>/session.jsonl` lists the
session's tasks in order.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from abc_harness.agent.loop import run_agent_task
from abc_harness.agent.model import ModelClient
from abc_harness.execution.figures import load_index
from abc_harness.execution.limits import Budget
from abc_harness.execution.report import metric_rows
from abc_harness.execution.runner import Runner
from abc_harness.execution.task import DecideFn, RunRecord, new_task_id
from abc_harness.literature.library import Literature
from abc_harness.tools.base import AskFn

FULL_TASKS = 5  # the latest tasks shown in full; older ones get one line
MAX_ANSWER_CHARS = 1500


@dataclass
class Turn:
    question: str
    task_id: str
    artifact_dir: Path
    status: str
    stop_reason: str
    summary: str | None


class ChatSession:
    def __init__(self, runs_root: Path, papers: list[Path] | None = None) -> None:
        self.runs_root = runs_root
        self.session_id = new_task_id()
        self.dir = runs_root / "sessions" / self.session_id
        self.dir.mkdir(parents=True)
        self.papers: list[Path] = list(papers or [])
        self.turns: list[Turn] = []

    def run_turn(
        self,
        question: str,
        model: ModelClient,
        runner: Runner,
        ask: AskFn,
        review: DecideFn,
        budget: Callable[[], Budget] = Budget,
        literature: Literature | None = None,
        redact: Callable[[str], str] | None = None,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        on_start: Callable[[Path], None] | None = None,
    ) -> Turn:
        """Run one request as a new task. A KeyboardInterrupt is recorded as an interrupted turn and re-raised."""
        started: list[Path] = []

        def start(artifact_dir: Path) -> None:
            started.append(artifact_dir)
            if on_start:
                on_start(artifact_dir)

        try:
            result = run_agent_task(
                question, model, runner, ask, review, runs_root=self.runs_root, budget=budget(), redact=redact,
                literature=literature, on_start=start, papers=self.papers, on_event=on_event,
                preface=self.preface(), previous_tasks={t.task_id: t.artifact_dir for t in self.turns},
                session_id=self.session_id,
            )  # fmt: skip
            turn = Turn(question, result.task_id, result.artifact_dir, result.status, result.stop_reason, result.summary)
        except KeyboardInterrupt:
            if started:
                manifest = _read_json(started[0] / "manifest.json") or {}
                self._record(Turn(question, started[0].name, started[0], manifest.get("status", "failed"),
                                  manifest.get("stop_reason", "interrupted by researcher"), None))  # fmt: skip
            raise
        self._record(turn)
        return turn

    def _record(self, turn: Turn) -> None:
        self.turns.append(turn)
        line = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"), "turn": len(self.turns),
                "question": turn.question, "task_id": turn.task_id, "task_dir": str(turn.artifact_dir),
                "status": turn.status, "stop_reason": turn.stop_reason}  # fmt: skip
        with (self.dir / "session.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def preface(self) -> str:
        """The earlier tasks, written from their records, for the first message of the next task."""
        if not self.turns:
            return ""
        lines = [
            "## Earlier in this conversation (written by the harness from its records)",
            "",
            ("Each earlier request ran as its own task. Their files are read-only under `previous/<task_id>/`, "
            "for example `previous/<task_id>/report.md`; read them with read_file when you need a detail. "
            "This request is a new task: propose a new plan if it needs a simulation, and find a paper again "
            "with search_papers before you cite it here."),
        ]
        older = self.turns[:-FULL_TASKS]
        if older:
            lines += ["", "Older tasks:"]
            lines += [f"- Task {i} `{t.task_id}` ({t.status}): {_one_line(t.question)}"
                      for i, t in enumerate(older, start=1)]  # fmt: skip
        for i, turn in enumerate(self.turns[len(older):], start=len(older) + 1):
            lines += ["", *_describe(i, turn)]
        return "\n".join(lines)


def _describe(number: int, turn: Turn) -> list[str]:
    lines = [f"### Task {number}: `{turn.task_id}` ({turn.status}: {turn.stop_reason})",
             f"Researcher asked: {turn.question.strip()}"]  # fmt: skip
    plan = _read_json(turn.artifact_dir / "plan.json")
    if plan:
        configs = ", ".join(c["name"] for c in plan.get("configurations", []))
        lines.append(f"Plan run: {plan.get('title')} ({plan.get('simulator')}; configurations {configs}; "
                     f"seeds {plan.get('seeds')})")  # fmt: skip
        records = [RunRecord(**r) for r in _read_json(turn.artifact_dir / "results.json") or []]
        if records:
            metrics = plan.get("metrics", [])
            lines.append("Results (mean ± sample standard deviation over completed runs, n runs):")
            for name, cells in metric_rows(records, metrics):
                lines.append(f"- {name}: " + "; ".join(f"{m} {c}" for m, c in zip(metrics, cells, strict=True)))
        validation = _read_json(turn.artifact_dir / "validation.json")
        if validation:
            lines.append(f"Validation check {'passed' if validation['passed'] else 'failed'}: mean "
                         f"{validation['metric']} {validation['mean']}")  # fmt: skip
    else:
        lines.append("No plan was run.")
    figures = load_index(turn.artifact_dir)
    if figures:
        lines.append("Figures: " + "; ".join(f"`{n}` ({f['caption']})" for n, f in figures.items()))
    if turn.summary:
        answer = turn.summary.strip()
        if len(answer) > MAX_ANSWER_CHARS:
            answer = answer[:MAX_ANSWER_CHARS] + f" [cut; the full answer is in previous/{turn.task_id}/report.md]"
        lines.append(f"Your final answer then: {answer}")
    return lines


def _one_line(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
