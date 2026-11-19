"""Per-task limits: active runtime and LLM calls (AGENTS.md hard rule 4)."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

DEFAULT_TIME_LIMIT_SECONDS = 30 * 60
DEFAULT_LLM_CALL_LIMIT = 500


class LimitReached(Exception):
    """Raised when a task exhausts one of its limits."""

    def __init__(self, limit: str, detail: str) -> None:
        super().__init__(f"{limit} limit reached: {detail}")
        self.limit = limit


class Budget:
    """Tracks active runtime and LLM calls for one task.

    Active runtime excludes time spent inside `waiting_for_human()`, so a
    researcher who reads a plan slowly does not use up simulation time, and
    time spent inside `parsing_pdf()`: the limit exists to stop a model that
    spins, and a PDF parse is not the model working. The parser has its own
    timeout instead (`literature.pdf.PARSE_TIMEOUT_SECONDS`).
    """

    def __init__(
        self,
        time_limit_seconds: float = DEFAULT_TIME_LIMIT_SECONDS,
        llm_call_limit: int = DEFAULT_LLM_CALL_LIMIT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.time_limit_seconds = time_limit_seconds
        self.llm_call_limit = llm_call_limit
        self.llm_calls = 0
        self.waiting_seconds = 0.0
        self.parsing_seconds = 0.0
        self._clock = clock
        self._started = clock()

    @property
    def active_seconds(self) -> float:
        return self._clock() - self._started - self.waiting_seconds - self.parsing_seconds

    @property
    def remaining_seconds(self) -> float:
        return self.time_limit_seconds - self.active_seconds

    @contextmanager
    def waiting_for_human(self) -> Iterator[None]:
        began = self._clock()
        try:
            yield
        finally:
            self.waiting_seconds += self._clock() - began

    @contextmanager
    def parsing_pdf(self) -> Iterator[None]:
        began = self._clock()
        try:
            yield
        finally:
            self.parsing_seconds += self._clock() - began

    def check_time(self) -> None:
        if self.remaining_seconds <= 0:
            raise LimitReached("time", f"{self.active_seconds:.1f}s of {self.time_limit_seconds:.0f}s active runtime")

    def count_llm_call(self) -> None:
        if self.llm_calls >= self.llm_call_limit:
            raise LimitReached("llm_calls", f"{self.llm_calls} of {self.llm_call_limit} calls used")
        self.llm_calls += 1
