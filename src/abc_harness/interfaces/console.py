"""Terminal output shared by every command: live trace events and the run statistics at the end."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from abc_harness.agent.model import price_for
from abc_harness.execution.trace import read_trace, summarize_trace

Write = Callable[[str], None]

PREVIEW_CHARS = 200


class Console:
    """Show concise progress from redacted trace events."""

    def __init__(self, write: Write = print, color: bool | None = None) -> None:
        self.write = write
        self.color = sys.stdout.isatty() and "NO_COLOR" not in os.environ if color is None else color

    def __call__(self, event: dict[str, Any]) -> None:
        for line in describe_event(event):
            self.print_line(line)

    def print_line(self, line: str) -> None:
        self.write(self._paint(line))

    def _paint(self, line: str) -> str:
        if not self.color:
            return line
        if line.startswith("PASS:"):
            return "\033[32mPASS\033[0m" + line[4:]
        if line.startswith("!"):
            return f"\033[31m{line}\033[0m"
        return line


def _short(value: Any, limit: int = PREVIEW_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def describe_event(e: dict[str, Any]) -> list[str]:
    """Show an action when it starts, an error if it fails, and the final answer in full."""
    kind = e.get("event")
    if kind == "model_call_started":
        action = "Summarizing context" if e.get("purpose") == "summary" else "Waiting for the model"
        cap = e.get("connect_timeout_seconds")
        if e.get("call") == 1 and cap is not None:
            action += f" (connect timeout up to {cap:g}s)"
        return [action]
    if kind == "model_retry":
        return [f"{e.get('reason', '')} Retry {e.get('retry')}/{e.get('max_retries')} in {e.get('delay_seconds', 0):.1f}s."]
    if kind == "model_call" and e.get("stop_reason") == "end_turn" and not e.get("tool_uses") and e.get("text"):
        return [e["text"].strip()]
    if kind == "tool_started":
        return [f"Using {_short(e.get('name', ''))}"]
    if kind == "tool_call" and e.get("is_error"):
        return [f"! {_short(e.get('tool', ''))}: {_short(e.get('result', ''))}"]
    if kind == "pdf_parse_started":
        return [f"Parsing {_short(e.get('pdf', ''))}"]
    if kind == "run_started":
        return [f"Running simulation {_short(e.get('run_id', ''))}"]
    if kind == "run_finished" and e.get("status") != "completed":
        detail = f": {_short(e['error'])}" if e.get("error") else ""
        return [f"! Simulation {_short(e.get('run_id', ''))} {e.get('status')}{detail}"]
    if kind == "validation_finished":
        return ["Validation passed" if e.get("passed") else "! Validation failed"]
    if kind == "sandbox_finished" and (e.get("timed_out") or e.get("exit_code") != 0):
        reason = "timed out" if e.get("timed_out") else f"exited with code {e.get('exit_code')}"
        return [f"! Sandbox command {reason}"]
    if kind == "figure_finished" and not e.get("ok"):
        return [f"! Figure failed: {_short(e.get('error', ''))}"]
    if kind in ("pdf_parse_failed", "error", "cleanup_failed"):
        return [f"! {kind.replace('_', ' ')}: {_short(e.get('error', ''))}"]
    if kind == "limit_reached":
        return [f"! Limit reached: {_short(e.get('detail', ''))}"]
    return []


def task_summary(task_dir: Path) -> list[str]:
    """Run statistics for the terminal: time, model calls and tokens, tool calls, and simulation runs.

    Experiment results stay in report.md; this is about what the task used, not what it measured.
    """
    manifest = _read_json(task_dir / "manifest.json") or {}
    lines = ["", f"── Run statistics of task {manifest.get('task_id', task_dir.name)} ──",
             f"Status: {manifest.get('status')} ({manifest.get('stop_reason')})"]  # fmt: skip
    records = _read_json(task_dir / "results.json") or []
    trace = summarize_trace(task_dir / "trace.jsonl") if (task_dir / "trace.jsonl").exists() else {}
    tokens = trace.get("tokens", {})
    cached = tokens.get("cache_read_input_tokens", 0)
    tokens_in = tokens.get("input_tokens", 0) + cached + tokens.get("cache_creation_input_tokens", 0)
    time_line = (f"Time: {manifest.get('active_seconds', 0):.1f}s active of "
                 f"{(manifest.get('limits') or {}).get('time_limit_seconds', 0):.0f}s, "
                 f"{manifest.get('waiting_seconds', 0):.1f}s waiting for you")  # fmt: skip
    if manifest.get("pdf_parse_seconds"):
        time_line += f", {manifest['pdf_parse_seconds']:.1f}s parsing PDFs (not counted)"
    lines.append(time_line)
    if trace.get("model_calls"):
        lines.append(f"Model: {trace['model_calls']} calls of {(manifest.get('limits') or {}).get('llm_call_limit')}, "
                     f"{trace.get('model_latency_seconds', 0):.1f}s waiting for answers; tokens {tokens_in:,} in "
                     f"({cached:,} from cache), {tokens.get('output_tokens', 0):,} out")  # fmt: skip
    if trace.get("model_calls"):
        lines.append(estimated_cost_line(task_dir / "trace.jsonl", str(manifest.get("model") or "")))
    if trace.get("tool_calls"):
        calls = ", ".join(f"{name} {n}" for name, n in sorted(trace["tool_calls"].items()))
        lines.append(f"Tools: {calls}; {trace.get('tool_errors', 0)} refused or failed")
    if records:
        done = sum(r.get("status") == "completed" for r in records)
        lines.append(f"Simulation runs: {done} of {len(records)} completed")
    lines.append(f"Report: {task_dir / 'report.md'}")
    return lines


def estimated_cost(trace_file: Path, default_model: str = "") -> tuple[float, set[str], set[str]]:
    """(USD, models priced, models without a known price) over every model call, summary calls included.

    Each call is priced by the model that answered it (a server-side fallback may answer with another model),
    from its own usage: uncached input, output (thinking included), cache reads, and cache writes.
    """
    total, priced, unknown = 0.0, set(), set()
    for e in read_trace(trace_file):
        if e["event"] not in ("model_call", "compaction"):
            continue
        model = str(e.get("model") or default_model)
        price = price_for(model)
        if price is None:
            unknown.add(model or "unknown")
            continue
        priced.add(model)
        when = datetime.fromisoformat(e["ts"]) if e.get("ts") else None  # DeepSeek prices by time of day
        total += price.cost(e.get("usage") or {}, when)
    return total, priced, unknown


def estimated_cost_line(trace_file: Path, default_model: str = "") -> str:
    total, priced, unknown = estimated_cost(trace_file, default_model)
    if not priced:
        return f"Estimated cost: unknown (no list price for {', '.join(sorted(unknown))})"
    line = f"Estimated cost: ${total:.2f} at list prices for {', '.join(sorted(priced))} (an estimate, not a bill)"
    if unknown:
        line += f"; calls to {', '.join(sorted(unknown))} are not included"
    return line


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
