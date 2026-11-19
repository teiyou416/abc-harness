"""Ask the researcher a clarification question; the wait does not count as active runtime."""

from __future__ import annotations

from typing import Any

from abc_harness.tools.base import ToolContext, ToolError

SPEC: dict[str, Any] = {
    "name": "ask_researcher",
    "description": "Ask the researcher one clarification question and wait for the answer. Use only when a "
    "missing detail would change what the result means.",
    "input_schema": {
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
    },
}


def run(ctx: ToolContext, args: dict[str, Any]) -> str:
    question = str(args.get("question", "")).strip()
    if not question:
        raise ToolError("question must not be empty")
    ctx.task.trace.event("human_wait_started", reason="clarification", question=question)
    with ctx.task.budget.waiting_for_human():
        answer = ctx.ask(question)
    ctx.clarifications.append((question, answer))
    ctx.task.trace.event("researcher_answer", answer=answer)
    return answer or "(the researcher gave no answer; choose a sensible default and say so in the plan)"
