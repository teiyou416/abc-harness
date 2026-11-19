"""Append-only event log for one task: `trace.jsonl` in the artifact directory."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class Trace:
    """Writes one JSON object per line and flushes after every event.

    Flushing on every write keeps the trace readable after a crash or a kill.
    Every line passes through `redact` first, so a secret that reaches an event
    by accident (for example inside an error message) is never written. An
    optional `listener` receives each event as written, for live display.
    """

    def __init__(
        self,
        path: Path,
        redact: Callable[[str], str] | None = None,
        listener: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.path = path
        self._redact = redact or (lambda text: text)
        self._listener = listener
        self._file = path.open("a", encoding="utf-8")

    def event(self, kind: str, **fields: Any) -> None:
        record = {"ts": datetime.now(UTC).isoformat(timespec="milliseconds"), "event": kind, **fields}
        line = self._redact(json.dumps(record, ensure_ascii=False, default=str))
        self._file.write(line + "\n")
        self._file.flush()
        if self._listener:
            # The listener sees the event exactly as written, after redaction.
            self._listener(json.loads(line))

    def close(self) -> None:
        self._file.close()


def read_trace(path: Path) -> list[dict[str, Any]]:
    """Return every event in a trace file, in order."""
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def summarize_trace(path: Path) -> dict[str, Any]:
    """Count model calls, tokens, latency, tool calls, and errors in one trace."""
    events = read_trace(path)
    calls = [e for e in events if e["event"] == "model_call"]
    tools = [e for e in events if e["event"] == "tool_call"]
    finished = next((e for e in reversed(events) if e["event"] == "task_finished"), {})
    tokens: Counter[str] = Counter()
    for call in calls:
        tokens.update({k: v for k, v in (call.get("usage") or {}).items() if isinstance(v, int)})
    return {
        "status": finished.get("status", "unfinished"),
        "stop_reason": finished.get("stop_reason"),
        "active_seconds": finished.get("active_seconds"),
        "model_calls": len(calls),
        "model_latency_seconds": round(sum(c.get("latency_seconds", 0) for c in calls), 3),
        "tokens": dict(tokens),
        "tool_calls": dict(Counter(t["tool"] for t in tools)),
        "tool_errors": sum(1 for t in tools if t.get("is_error")),
        "errors": [e.get("error") for e in events if e["event"] == "error"],
        "pdf_parses": [{k: e.get(k) for k in ("pdf", "seconds", "cached")} for e in events
                       if e["event"] == "pdf_parse_finished"],
        "simulation_runs": dict(Counter(e["status"] for e in events if e["event"] == "run_finished")),
    }
