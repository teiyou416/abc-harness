"""Command-line interface: `image build`, `run`, `ask`, `trace summary`, and `export`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from abc_harness.agent.model import DEFAULT_EFFORT, DEFAULT_MODEL
from abc_harness.agent.secrets import DEFAULT_ENV_FILE, MissingSecret, Secrets
from abc_harness.execution.export import ExportError, export_task
from abc_harness.execution.limits import DEFAULT_LLM_CALL_LIMIT, DEFAULT_TIME_LIMIT_SECONDS, Budget
from abc_harness.execution.runner import DockerRunner, RunnerError, build_image
from abc_harness.execution.task import TaskResult, run_task
from abc_harness.execution.trace import summarize_trace
from abc_harness.literature.pdf import PARSER_IMAGE
from abc_harness.planning.plan import Plan, PlanError, load_plan
from abc_harness.simulators import SIMULATORS, SimulatorError, get_simulator

Read = Callable[[str], str]
Write = Callable[[str], None]


S2_KEY = "SEMANTIC_SCHOLAR_API_KEY"  # optional; without it literature search uses OpenAlex only
PDF_PARSER = "pdf-parser"
PDF_PARSER_CONTEXT = Path(__file__).resolve().parents[2] / "docker" / "mineru"

def prompt_decision(
    plan: Plan, read: Read | None = None, write: Write = print, allow_revise: bool = False
) -> tuple[str, str]:
    """Show the plan and ask the researcher to decide.

    End of input or an unreadable terminal counts as a rejection, so a closed
    terminal never starts a run.
    """
    read = read or input
    choices = "approve/revise/reject" if allow_revise else "approve/reject"
    write(plan.render())
    write("")
    while True:
        try:
            answer = read(f"Approve this plan? [{choices}]: ").strip().lower()
        except (EOFError, OSError):
            return "reject", "no answer (input closed)"
        if answer in ("approve", "a", "yes", "y"):
            return "approve", ""
        if answer in ("reject", "no", "n") or (answer == "r" and not allow_revise):
            return "reject", _read_optional(read, "Reason (optional): ")
        if allow_revise and answer in ("revise", "r"):
            comment = _read_optional(read, "What should change? ")
            if comment:
                return "revise", comment
            write("A revision needs a comment.")
            continue
        write(f"Please answer one of: {choices}.")


def prompt_answer(question: str, read: Read | None = None, write: Write = print) -> str:
    read = read or input
    write(f"\nQuestion from the agent: {question}")
    return _read_optional(read, "Your answer: ")


def _read_optional(read: Read, prompt: str) -> str:
    try:
        return read(prompt).strip()
    except (EOFError, OSError):
        return ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="abc-harness", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    image = sub.add_parser("image", help="manage execution images")
    image_sub = image.add_subparsers(dest="image_command", required=True)
    build = image_sub.add_parser("build", help="build the execution image of each simulator and the PDF parser image")
    build.add_argument("--only", default="all", choices=["all", *sorted(SIMULATORS), PDF_PARSER],
                       help="build one image instead of all")  # fmt: skip

    def task_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--runs-dir", type=Path, default=Path("runs"), help="where artifact directories go")
        p.add_argument("--time-limit-seconds", type=float, default=DEFAULT_TIME_LIMIT_SECONDS,
                       help="active runtime limit per task (default: 1800)")  # fmt: skip
        p.add_argument("--quiet", action="store_true",
                       help="do not print each model call, tool call, and run as it happens")  # fmt: skip

    run = sub.add_parser("run", help="review a plan file (TOML or plan.json) and run it after approval")
    run.add_argument("plan", type=Path)
    task_options(run)

    ask = sub.add_parser("ask", help="describe an experiment; the agent drafts a plan for your approval")
    ask.add_argument("question", help="the research question, in any language")
    ask.add_argument("--model", default=DEFAULT_MODEL)
    ask.add_argument("--effort", default=DEFAULT_EFFORT, choices=["low", "medium", "high", "xhigh", "max"])
    ask.add_argument("--llm-call-limit", type=int, default=DEFAULT_LLM_CALL_LIMIT)
    ask.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help="file holding API keys")
    ask.add_argument("--paper", type=Path, action="append", default=[], metavar="PDF",
                     help="a paper the agent should read, as a PDF file; repeat for several")  # fmt: skip
    task_options(ask)

    trace = sub.add_parser("trace", help="inspect task traces")
    trace_sub = trace.add_subparsers(dest="trace_command", required=True)
    export = sub.add_parser("export", help="package a task's modified simulator source")
    export.add_argument("task", help="runs/<task_id>, or a task ID under --runs-dir")
    export.add_argument("--runs-dir", type=Path, default=Path("runs"))
    summary = trace_sub.add_parser("summary", help="summarize model calls, tokens, tools, and errors")
    summary.add_argument("task_dir", type=Path, help="runs/<task_id>")
    return parser


def _check_papers(papers: list[Path]) -> str | None:
    """Why the --paper files cannot be used, or None. Checked before a task starts."""
    for path in papers:
        if not path.is_file():
            return f"--paper {path}: no such file"
        with path.open("rb") as f:
            if f.read(5) != b"%PDF-":
                return f"--paper {path}: not a PDF file"
    if papers:
        try:
            DockerRunner().image_info(PARSER_IMAGE)
        except RunnerError:
            return f"--paper needs the PDF parser image {PARSER_IMAGE}; run `abc-harness image build --only {PDF_PARSER}`"
    return None


def _announce(artifact_dir: Path) -> None:
    print(f"Task directory: {artifact_dir} (paths shown during review are relative to it)")


def _print_result(result: TaskResult) -> int:
    for line in task_summary(result.artifact_dir):
        print(line)
    print(f"Artifacts: {result.artifact_dir}")
    if not (result.artifact_dir / "raw").exists():
        print("No simulation was run.")
    return 0 if result.status in ("completed", "rejected", "not_executed") else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "image":
        names = [*sorted(SIMULATORS), PDF_PARSER] if args.only == "all" else [args.only]
        for name in names:
            if name == PDF_PARSER:
                context, tag = PDF_PARSER_CONTEXT, PARSER_IMAGE
            else:
                context, tag = get_simulator(name).docker_context, get_simulator(name).image_tag
            print(f"Built {tag} ({build_image(context, tag)})")
        return 0

    if args.command == "export":
        task_dir = Path(args.task) if Path(args.task).is_dir() else args.runs_dir / args.task
        try:
            archive = export_task(task_dir)
        except ExportError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(f"Exported: {archive}")
        return 0

    if args.command == "trace":
        print(json.dumps(summarize_trace(args.task_dir / "trace.jsonl"), indent=2, ensure_ascii=False))
        return 0

    if args.command == "ask":
        from abc_harness.agent.loop import run_agent_task
        from abc_harness.agent.model import AnthropicModel
        from abc_harness.literature import HttpFetcher, Literature

        problem = _check_papers(args.paper)
        if problem:
            print(f"error: {problem}", file=sys.stderr)
            return 2
        secrets = Secrets.load(args.env_file, names=("ANTHROPIC_API_KEY", S2_KEY))
        try:
            model = AnthropicModel(secrets.get("ANTHROPIC_API_KEY"), model=args.model, effort=args.effort)
        except MissingSecret as e:
            print(f"error: {e.args[0]}", file=sys.stderr)
            return 2
        literature = Literature(HttpFetcher(), secrets.get(S2_KEY) if secrets.has(S2_KEY) else None)
        result = run_agent_task(
            args.question,
            model,
            DockerRunner(),
            prompt_answer,
            lambda plan: prompt_decision(plan, allow_revise=True),
            runs_root=args.runs_dir,
            budget=Budget(time_limit_seconds=args.time_limit_seconds, llm_call_limit=args.llm_call_limit),
            redact=secrets.redact,
            literature=literature,
            on_start=_announce,
            papers=args.paper,
            on_event=None if args.quiet else Console(),
        )
        summary = (result.artifact_dir / "report.md").read_text(encoding="utf-8")
        if "## Agent summary" in summary:
            print("\n" + summary.split("## Agent summary", 1)[1].split("\n## ", 1)[0].strip())
        return _print_result(result)

    try:
        load_plan(args.plan)
    except (PlanError, SimulatorError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    result = run_task(
        args.plan,
        DockerRunner(),
        prompt_decision,
        runs_root=args.runs_dir,
        budget=Budget(time_limit_seconds=args.time_limit_seconds),
        on_start=_announce,
        on_event=None if args.quiet else Console(),
    )
    return _print_result(result)


# ----- live progress and the final summary -----

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
    if trace.get("tool_calls"):
        calls = ", ".join(f"{name} {n}" for name, n in sorted(trace["tool_calls"].items()))
        lines.append(f"Tools: {calls}; {trace.get('tool_errors', 0)} refused or failed")
    if records:
        done = sum(r.get("status") == "completed" for r in records)
        lines.append(f"Simulation runs: {done} of {len(records)} completed")
    lines.append(f"Report: {task_dir / 'report.md'}")
    return lines


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
