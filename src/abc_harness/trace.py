"""Append-only event log for one task: `trace.jsonl` in the artifact directory."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class Trace:
    """Writes one JSON object per line and flushes after every event.

    Flushing on every write keeps the trace readable after a crash or a kill.
    Callers pass plain data only; the trace never reads the environment, so it
    cannot pick up the API key by accident.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file = path.open("a", encoding="utf-8")

    def event(self, kind: str, **fields: Any) -> None:
        record = {"ts": datetime.now(UTC).isoformat(timespec="milliseconds"), "event": kind, **fields}
        self._file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def read_trace(path: Path) -> list[dict[str, Any]]:
    """Return every event in a trace file, in order."""
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
