"""Terminal output shared by every command: live trace events and the run statistics at the end."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from abc_harness.agent.model import PRICES_PER_MTOK
from abc_harness.execution.trace import read_trace, summarize_trace

Write = Callable[[str], None]

PREVIEW_CHARS = 200


class Console:
    """Prints each trace event as it happens, so the researcher can follow the agent and the runs.

    It receives events after redaction (see `Trace`), so it can print nothing the trace would not hold.
    Thinking is the model's summarized reasoning, shown dimmed; tool inputs and results are shortened,
    and the full text is in `trace.jsonl` and `history.md`.
    """

    def __init__(self, write: Write = print, color: bool | None = None) -> None:
        self.write = write
        self.color = sys.stdout.isatty() and "NO_COLOR" not in os.environ if color is None else color

    def __call__(self, event: dict[str, Any]) -> None:
        for line in describe_event(event):
            self.write(self._paint(line))

    def _paint(self, line: str) -> str:
        if not self.color:
            return line
        if line.startswith("  thinking:"):
            return f"\033[2m{line}\033[0m"
        if line.startswith("!"):
            return f"\033[31m{line}\033[0m"
        if line.startswith(("◆", "▣")):
            return f"\033[1m{line}\033[0m"
        return line


def _short(value: Any, limit: int = PREVIEW_CHARS) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _indent(label: str, text: str) -> list[str]:
    lines = text.strip().splitlines() or [""]
    pad = " " * (len(label) + 4)
    return [f"  {label}: {lines[0]}"] + [pad + line for line in lines[1:]]


def describe_event(e: dict[str, Any]) -> list[str]:
    """Terminal lines for one trace event; events with nothing to show give no lines."""
    kind = e.get("event")
    if kind == "model_call_started":
        what = "summarizing the context window" if e.get("purpose") == "summary" else "waiting for the model"
        return [f"… model call {e.get('call')}: {what}"]
    if kind == "model_call":
        usage = e.get("usage") or {}
        tokens_in = sum(usage.get(k, 0) for k in ("input_tokens", "cache_read_input_tokens",
                                                   "cache_creation_input_tokens"))  # fmt: skip
        lines = [(f"◆ model call {e.get('call')}: {e.get('latency_seconds', 0):.1f}s, "
                 f"{tokens_in:,} tokens in, {usage.get('output_tokens', 0):,} out")]  # fmt: skip
        for thought in e.get("thinking") or []:
            lines += _indent("thinking", thought)
        if e.get("text"):
            lines += _indent("says", e["text"])
        lines += [f"  → {t['name']} {_short(t.get('input'))}" for t in e.get("tool_uses") or []]
        return lines
    if kind == "tool_call":
        status = "error" if e.get("is_error") else "ok"
        mark = "!" if e.get("is_error") else " "
        images = f" [{len(e['images'])} image(s)]" if e.get("images") else ""
        return [(f"{mark} ← {e.get('tool')} {status} ({e.get('duration_seconds', 0):.1f}s){images}: "
                f"{_short(e.get('result', ''))}")]  # fmt: skip
    if kind == "compaction":
        return [(f"⟳ context compressed after window {e.get('from_window')} "
                f"(about {e.get('estimated_input_tokens', 0):,} tokens)")]  # fmt: skip
    if kind == "plan_proposed":
        return [f"▣ plan {str(e.get('plan_version'))[:12]} proposed: {e.get('runs')} simulation runs"]
    if kind == "plan_decision":
        comment = f": {e['comment']}" if e.get("comment") else ""
        return [f"▣ researcher decided {e.get('decision')}{comment}"]
    if kind == "researcher_answer":
        return [f"  researcher answered: {_short(e.get('answer', ''))}"]
    if kind in ("file_written", "file_edited"):
        return [f"  ✎ {'wrote' if kind == 'file_written' else 'edited'} {e.get('path')}"]
    if kind == "sandbox_started":
        return [f"  $ {_short(e.get('command', ''))}"]
    if kind == "sandbox_finished":
        result = "timed out" if e.get("timed_out") else f"exit {e.get('exit_code')}"
        return [f"{'!' if result != 'exit 0' else ' '}   {result} ({e.get('duration_seconds', 0):.1f}s), log {e.get('log')}"]
    if kind == "edits_frozen":
        return [f"▣ edits frozen: {', '.join(e.get('files') or []) or 'no file changed'}"]
    if kind == "validation_finished":
        verdict = "passed" if e.get("passed") else "FAILED"
        mark = "▣" if e.get("passed") else "!"
        return [(f"{mark} validation check {verdict}: mean {e.get('mean')} over {e.get('n')} runs, "
                f"required {e.get('expected')} ± {e.get('tolerance')}")]  # fmt: skip
    if kind == "run_started":
        return [f"▶ simulation run {e.get('run_id')} started"]
    if kind == "run_finished":
        metrics = " ".join(f"{k}={v:.6g}" for k, v in (e.get("metrics") or {}).items())
        error = f" ({e['error']})" if e.get("error") else ""
        mark = " " if e.get("status") == "completed" else "!"
        return [f"{mark}   {e.get('run_id')}: {e.get('status')}{error} in {e.get('duration_seconds') or 0:.1f}s {metrics}"]
    if kind == "figure_started":
        return [f"  drawing figure {e.get('name')} in the plot image"]
    if kind == "figure_finished":
        if e.get("ok"):
            return [f"  figure {e.get('name')}: saved {e.get('png')} ({e.get('duration_seconds', 0):.1f}s)"]
        return [f"! figure {e.get('name')} failed: {_short(e.get('error', ''))}"]
    if kind == "pdf_parse_started":
        return [(f"  parsing {e.get('pdf')} with the PDF parser (up to {e.get('timeout_seconds', 0) // 60:.0f} min, "
                "not counted toward the time limit)")]  # fmt: skip
    if kind == "pdf_parse_finished":
        how = "reused from the cache" if e.get("cached") else f"parsed in {e.get('seconds', 0):.0f}s"
        return [f"  {e.get('pdf')}: {how}"]
    if kind in ("pdf_parse_failed", "error", "cleanup_failed"):
        return [f"! {kind.replace('_', ' ')}: {e.get('error')}"]
    if kind == "limit_reached":
        return [f"! limit reached: {e.get('detail')}"]
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
        prices = next((p for name, p in PRICES_PER_MTOK.items() if model.startswith(name)), None)
        if prices is None:
            unknown.add(model or "unknown")
            continue
        priced.add(model)
        usage = e.get("usage") or {}
        tokens = (usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                  usage.get("cache_read_input_tokens", 0), usage.get("cache_creation_input_tokens", 0))  # fmt: skip
        total += sum(n * price for n, price in zip(tokens, prices, strict=True)) / 1_000_000
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
