"""Terminal output shared by every command: live trace events and the run statistics at the end."""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from abc_harness.agent.model import price_for
from abc_harness.execution.trace import read_trace, summarize_trace

Write = Callable[[str], None]

PREVIEW_CHARS = 200
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
# The tool argument that best says what a call is about, in this order.
TARGET_KEYS = ("path", "pattern", "query", "command", "name", "simulator", "paper", "figure")


class Console:
    """Live progress: one status line, redrawn in place, says what the task is doing now; each tool call,
    milestones, errors, and the final answer stay on screen above it. Details stay in trace.jsonl and
    history.md.

    The status line is drawn only on a terminal (`live`); elsewhere only the lasting lines are written.
    """

    def __init__(self, write: Write = print, color: bool | None = None, live: bool | None = None,
                 stream: TextIO | None = None, tick_seconds: float = 0.1) -> None:  # fmt: skip
        self.write = write
        tty = sys.stdout.isatty()
        self.color = tty and "NO_COLOR" not in os.environ if color is None else color
        self.live = tty if live is None else live
        self.stream = stream or sys.stdout
        self.tick_seconds = tick_seconds
        self.status = ""
        self._lock = threading.RLock()
        self._drawn = False
        self._frame = 0
        self._ticker: threading.Thread | None = None
        self._task_started = time.monotonic()
        self._pending_tools: list[dict[str, Any]] = []
        self._runs = self._validation_runs = self._started_runs = 0

    def __call__(self, event: dict[str, Any]) -> None:
        status, lines = self._describe(event)
        with self._lock:
            self._clear()
            for line in lines:
                self.write(self._paint(line))
            if status is not None:
                self.status = status
            self._draw()
        if self.status and self.live and self.tick_seconds and self._ticker is None:
            self._ticker = threading.Thread(target=self._tick, daemon=True)
            self._ticker.start()

    def print_line(self, line: str) -> None:
        with self._lock:
            self._clear()
            self.write(self._paint(line))
            self._draw()

    def idle(self) -> None:
        """Remove the status line, for example before the terminal reads input."""
        with self._lock:
            self._clear()
            self.status = ""

    def _tick(self) -> None:
        while True:
            time.sleep(self.tick_seconds)
            with self._lock:
                if self.status:
                    self._frame += 1
                    self._clear()
                    self._draw()

    def _clear(self) -> None:
        if self._drawn:
            self.stream.write("\r\033[K")
            self.stream.flush()
            self._drawn = False

    def _draw(self) -> None:
        if not (self.live and self.status):
            return
        elapsed = int(time.monotonic() - self._task_started)
        clock = f"{elapsed // 60}m{elapsed % 60:02d}s" if elapsed >= 60 else f"{elapsed}s"
        text = f"{SPINNER[self._frame % len(SPINNER)]} {self.status} · {clock}"
        width = max(20, shutil.get_terminal_size().columns - 1)
        text = text if len(text) <= width else text[: width - 1] + "…"
        self.stream.write("\r" + (f"\033[36m{text[0]}\033[0m{text[1:]}" if self.color else text))
        self.stream.flush()
        self._drawn = True

    def _paint(self, line: str) -> str:
        if not self.color:
            return line
        if line.startswith(("PASS:", "✓")):
            word = "PASS" if line.startswith("PASS:") else "✓"
            return f"\033[32m{word}\033[0m" + line[len(word):]
        if line.startswith("!"):
            return f"\033[31m{line}\033[0m"
        if line.startswith("●"):
            return f"\033[36m●\033[0m{line[1:]}"
        return line

    def _describe(self, e: dict[str, Any]) -> tuple[str | None, list[str]]:
        """The new status line (None keeps the current one, "" removes it) and the lines that stay."""
        kind = e.get("event")
        if kind == "task_started":
            self._task_started = time.monotonic()
            self._pending_tools, self._started_runs = [], 0
            return None, []
        if kind in ("human_wait_started", "task_finished"):
            return "", []
        if kind == "model_call_started":
            return ("Summarizing context" if e.get("purpose") == "summary" else "Thinking"), []
        if kind == "model_retry":
            return None, [(f"↻ {e.get('reason', '')} Retry {e.get('retry')}/{e.get('max_retries')} "
                           f"in {e.get('delay_seconds', 0):.1f}s.")]  # fmt: skip
        if kind == "model_call":
            self._pending_tools = list(e.get("tool_uses") or [])
            if e.get("stop_reason") == "end_turn" and not self._pending_tools and e.get("text"):
                return "", [e["text"].strip()]
            return None, []
        if kind == "tool_started":
            name = e.get("name", "")
            target = ""
            if self._pending_tools and self._pending_tools[0].get("name") == name:
                target = _target(self._pending_tools.pop(0).get("input"))
            action = name + (f" {target}" if target else "")
            return f"Using {action}", [f"● {action}"]
        if kind == "tool_call" and e.get("is_error"):
            return None, [f"! {e.get('tool', '')}: {_short(e.get('result', ''))}"]
        if kind == "pdf_parse_started":
            return f"Parsing {Path(str(e.get('pdf', ''))).name}", []
        if kind == "sandbox_started":
            return f"Sandbox: {_short(e.get('command', ''), 60)}", []
        if kind == "sandbox_finished" and (e.get("timed_out") or e.get("exit_code") != 0):
            reason = "timed out" if e.get("timed_out") else f"exited with code {e.get('exit_code')}"
            return None, [f"! Sandbox command {reason}"]
        if kind == "figure_started":
            return f"Drawing figure {e.get('name', '')}", []
        if kind == "figure_finished":
            if e.get("ok"):
                return None, [f"✓ Figure {e.get('name', '')} saved"]
            return None, [f"! Figure {e.get('name', '')} failed: {_short(e.get('error', ''))}"]
        if kind == "plan_proposed":
            self._runs, self._validation_runs = e.get("runs") or 0, e.get("validation_runs") or 0
            return None, []
        if kind == "plan_decision":
            self._started_runs = 0
            return None, [_decision_line(e, self._runs, self._validation_runs)]
        if kind == "run_started":
            self._started_runs += 1
            n = self._started_runs
            if n <= self._validation_runs:
                return f"Validation run {n}/{self._validation_runs}", []
            n -= self._validation_runs
            return (f"Running simulation {n}/{self._runs}" if self._runs else f"Running {e.get('run_id', '')}"), []
        if kind == "run_finished" and e.get("status") != "completed":
            detail = f": {_short(e['error'])}" if e.get("error") else ""
            return None, [f"! Simulation {e.get('run_id', '')} {e.get('status')}{detail}"]
        if kind == "validation_finished":
            return None, ["✓ Validation passed" if e.get("passed") else "! Validation failed"]
        if kind in ("pdf_parse_failed", "error", "cleanup_failed"):
            return None, [f"! {kind.replace('_', ' ')}: {_short(e.get('error', ''))}"]
        if kind == "library_paper_added":
            return None, [f"✓ Saved to the local library: {e.get('file', '')}"]
        if kind == "library_large":
            return None, [(f"! The local library {e.get('library')}/ holds {e.get('papers')} PDFs, more than "
                           f"{e.get('threshold')}; every task lists them all, so consider removing some.")]
        if kind == "limit_reached":
            return None, [f"! Limit reached: {_short(e.get('detail', ''))}"]
        return None, []


def _decision_line(e: dict[str, Any], runs: int, validation_runs: int) -> str:
    plan = f"Plan {str(e.get('plan_version', ''))[:12]}"
    decision = e.get("decision")
    if decision == "approve":
        extra = f", {validation_runs} validation runs" if validation_runs else ""
        return f"✓ {plan} approved ({runs} runs{extra})"
    if decision == "revise":
        return f"↺ {plan} sent back for revision"
    return f"✗ {plan} {decision or 'rejected'}"


def _target(args: Any) -> str:
    if not isinstance(args, dict):
        return ""
    for key in TARGET_KEYS:
        if isinstance(args.get(key), str) and args[key].strip():
            return _short(args[key], 60)
    return ""


def _short(value: Any, limit: int = PREVIEW_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


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
    lines += _evidence_lines(task_dir)
    lines.append(f"Report: {task_dir / 'report.md'}")
    return lines


def _evidence_lines(task_dir: Path, shown: int = 5) -> list[str]:
    """The verdict of the automatic `trace check`, with its problems when it did not pass."""
    check = _read_json(task_dir / "trace_check.json")
    if not check:
        return []
    passes = [line.removeprefix("PASS: ") for line in check["lines"] if line.startswith("PASS: ")]
    warnings = [line for line in check["lines"] if line.startswith("WARN: ")]
    if check["verdict"] == "PASS" and not warnings:
        return [f"Evidence check: PASS ({'; '.join(passes)})"]
    problems = [line for line in check["lines"] if not line.startswith(("PASS: ", "NOTE: "))]
    verdict = check["verdict"] + (f" with {len(warnings)} warning(s)" if warnings else "")
    lines = [f"Evidence check: {verdict}; details in trace_check.json"]
    lines += [f"  {p}" for p in problems[:shown]]
    if len(problems) > shown:
        lines.append(f"  … and {len(problems) - shown} more")
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
    return cost_line(*estimated_cost(trace_file, default_model))


def cost_line(total: float, priced: set[str], unknown: set[str]) -> str:
    if not priced:
        return f"Estimated cost: unknown (no list price for {', '.join(sorted(unknown))})"
    line = f"Estimated cost: ${total:.2f} at list prices for {', '.join(sorted(priced))} (an estimate, not a bill)"
    if unknown:
        line += f"; calls to {', '.join(sorted(unknown))} are not included"
    return line


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
