"""What every tool shares: the context it runs in and the two ways it can refuse or stop.

A tool module exports `SPEC` (the definition sent to the model) and
`run(ctx, args) -> str`. The harness, not the model, decides what a tool may
do: a refusal raises `ToolError`, whose message goes back to the model, and a
decision that ends the task raises `EndTask`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from abc_harness.execution.task import DecideFn, Task

AskFn = Callable[[str], str]


class ToolError(Exception):
    """A tool request the harness refused; the message goes back to the model."""


class EndTask(Exception):
    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status, self.reason = status, reason


@dataclass
class ToolContext:
    """The task state tools may read and change. The agent loop owns one per task."""

    task: Task
    ask: AskFn
    review: DecideFn
    clarifications: list[tuple[str, str]] = field(default_factory=list)
    execution: tuple[str, str] | None = None  # (status, reason) once run_plan has executed a plan


class ToolRun(Protocol):
    def __call__(self, ctx: ToolContext, args: dict[str, Any]) -> str: ...
