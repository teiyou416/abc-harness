"""Context window management (docs/development-plan.md, M2.5).

The agent's input is the system prompt (SOUL.md + rules.md), the tools, and
the current window's messages. Before every model call the harness estimates
the next input. Past the soft limit it compresses: the model summarizes the
window, and a new window starts from the original question, a task-state block
the harness writes from its own records, that summary, and the latest tool
results. `history.md` keeps every message verbatim across windows.

Numbers that matter (plan versions, decisions, measurements) never pass
through the summary; they come from the task-state block, which is generated
from the harness's records.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from abc_harness.literature.figures import image_tokens

if TYPE_CHECKING:
    from abc_harness.execution.task import Task
    from abc_harness.literature.library import Library

# A deliberately pessimistic ratio: real text averages closer to 4 characters
# per token, so estimates err towards compressing early, never late.
CHARS_PER_TOKEN = 3


@dataclass(frozen=True)
class ContextLimits:
    soft_limit: int = 106_496
    hard_limit: int = 131_072
    max_output_tokens: int = 16_384
    compact_max_tokens: int = 8_192
    tool_result_max_tokens: int = 8_192

    @property
    def max_input_tokens(self) -> int:
        """Input must leave room for a full reply inside the hard limit."""
        return self.hard_limit - self.max_output_tokens


def estimate_tokens(value: Any) -> int:
    """Text at CHARS_PER_TOKEN; an image block by its pixel size, not by the length of its base64 data."""
    if isinstance(value, str):
        return len(value) // CHARS_PER_TOKEN + 1
    images: list[int] = []

    def without_images(v: Any) -> Any:
        if isinstance(v, dict):
            if v.get("type") == "image" and isinstance(v.get("source"), dict):
                images.append(image_tokens(base64.b64decode(v["source"].get("data", ""))))
                return {"type": "image"}
            return {k: without_images(x) for k, x in v.items()}
        if isinstance(v, list):
            return [without_images(x) for x in v]
        return v

    text = json.dumps(without_images(value), ensure_ascii=False, default=str)
    return len(text) // CHARS_PER_TOKEN + 1 + sum(images)


def content_text(content: Any) -> str:
    """The text of a message or tool result content, with images replaced by a placeholder."""
    if isinstance(content, str):
        return content
    parts = []
    for block in content or []:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "image":
            parts.append("[image; viewed earlier, not repeated here]")
    return "\n".join(parts)


def cap_text(text: str, max_tokens: int, where: str) -> str:
    """Cut text to roughly max_tokens and say where the full text is."""
    max_chars = max_tokens * CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return text
    note = f"\n[cut: showing the first {{shown}} of {len(text)} characters; the full text is in {where}]"
    shown = max_chars - len(note) - 10
    return text[:shown] + note.format(shown=shown)


class History:
    """Appends every message of every window to `history.md`, with full tool results."""

    def __init__(self, path: Path, task_id: str) -> None:
        self.path = path
        self.window = 0
        path.write_text(f"# Conversation history of task {task_id}\n", encoding="utf-8")

    def start_window(self, reason: str) -> None:
        self.window += 1
        self._append(f"\n## Window {self.window}\n\n_{reason}_\n")

    def user_text(self, text: str, label: str = "user") -> None:
        self._append(f"\n### {label}\n\n{text}\n")

    def assistant(self, content: list[dict[str, Any]]) -> None:
        parts = ["\n### assistant\n"]
        for block in content:
            if block.get("type") == "text" and block.get("text"):
                parts.append(f"\n{block['text']}\n")
            elif block.get("type") == "tool_use":
                args = json.dumps(block.get("input"), ensure_ascii=False, indent=2)
                parts.append(f"\n**tool_use** `{block['name']}` (id `{block['id']}`)\n\n```json\n{args}\n```\n")
        self._append("".join(parts))

    def tool_result(self, tool_use_id: str, name: str, full_text: str, is_error: bool) -> None:
        label = "error" if is_error else "result"
        self._append(f"\n### tool {label}: `{name}` (id `{tool_use_id}`)\n\n```text\n{full_text}\n```\n")

    def _append(self, text: str) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(text)


def render_transcript(messages: list[dict[str, Any]]) -> str:
    """Plain-text form of a window for the summary call. Thinking blocks are left out."""
    lines = []
    for message in messages:
        content = message["content"]
        if isinstance(content, str):
            lines.append(f"[{message['role']}]\n{content}")
            continue
        for block in content:
            kind = block.get("type")
            if kind == "text" and block.get("text"):
                lines.append(f"[{message['role']}]\n{block['text']}")
            elif kind == "tool_use":
                lines.append(f"[tool call] {block['name']} {json.dumps(block.get('input'), ensure_ascii=False)}")
            elif kind == "tool_result":
                flag = " (error)" if block.get("is_error") else ""
                lines.append(f"[tool result{flag}]\n{content_text(block.get('content'))}")
    return "\n\n".join(lines)


def task_state(task: Task, clarifications: list[tuple[str, str]], library: Library | None = None) -> str:
    """The facts the next window must have exactly, written from the harness's own records."""
    from abc_harness.planning.approval import read_decisions

    lines = ["## Task state (written by the harness from its records; trust this over the summary)", ""]
    if task.plans:
        lines.append("Plan versions proposed:")
        for version, plan in task.plans.items():
            configs = ", ".join(c["name"] for c in plan.data["configurations"])
            lines.append(f"- `{version}`: {plan.data['title']} (configurations: {configs}; seeds: {plan.data['seeds']})")
    else:
        lines.append("No plan has been proposed yet.")
    decisions = read_decisions(task.artifact_dir)
    if decisions:
        lines += ["", "Researcher decisions, oldest first:"]
        lines += [f"- {d.decision} `{d.plan_version}`" + (f": {d.comment}" if d.comment else "") for d in decisions]
    if clarifications:
        lines += ["", "Clarification questions and the researcher's answers:"]
        lines += [f"- Q: {q}\n  A: {a}" for q, a in clarifications]
    if library is not None and library.papers:
        lines += ["", "Papers found by search_papers or supplied by the researcher (only these can be cited):"]
        for paper in library.papers.values():
            text = f"; full text in task/{library.full_texts[paper.id]}" if paper.id in library.full_texts else ""
            lines.append(f"- `{paper.id}`: {paper.title} ({paper.year}){text}")
            for label, saved in library.viewed.get(paper.id, {}).items():
                lines.append(f"  - viewed {label} (task/{saved[0]}); view it again to read new values")
    if task.executed is not None:
        from abc_harness.tools.run_plan import run_summary

        status = "completed" if all(r.status == "completed" for r in task.records) else "not fully completed"
        summary = run_summary(task, status, "see report")
        lines += ["", f"Executed plan `{task.executed.version}`. Results:", "```json",
                  json.dumps(summary["configurations"], ensure_ascii=False, indent=2), "```"]  # fmt: skip
    else:
        lines += ["", "No plan has been executed yet."]
    return "\n".join(lines)


def latest_tool_results(messages: list[dict[str, Any]]) -> str:
    """The tool results the agent has not reacted to yet, as text for the new window."""
    if not messages or messages[-1]["role"] != "user" or isinstance(messages[-1]["content"], str):
        return ""
    calls = {}
    if len(messages) >= 2 and messages[-2]["role"] == "assistant":
        calls = {b["id"]: b for b in messages[-2]["content"] if b.get("type") == "tool_use"}
    parts = []
    for block in messages[-1]["content"]:
        if block.get("type") != "tool_result":
            continue
        call = calls.get(block["tool_use_id"], {})
        args = json.dumps(call.get("input"), ensure_ascii=False)
        flag = " (error)" if block.get("is_error") else ""
        parts.append(f"### `{call.get('name', '?')}` {args}{flag}\n\n{content_text(block.get('content'))}")
    return "\n\n".join(parts)


def new_window_message(question: str, state: str, summary: str, latest: str) -> str:
    sections = [
        (
            "This conversation continues an earlier window that reached the context limit. "
            "The full earlier conversation is in `task/history.md`; read it with `read_file` when you need a detail."
        ),
        f"## Original question\n\n{question}",
        state,
        f"## Summary of the earlier window (written by the model)\n\n{summary}",
    ]
    if latest:
        sections.append(f"## Latest tool results, which you have not acted on yet\n\n{latest}")
    sections.append("Continue the task from here.")
    return "\n\n".join(sections)
