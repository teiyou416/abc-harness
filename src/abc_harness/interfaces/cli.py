"""Command-line interface: `image build`, `run`, `ask`, `chat`, `trace summary`, and `export`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from abc_harness.agent.model import (
    API_KEY_NAMES,
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    EFFORTS,
    MODELS,
    ModelUnavailable,
    make_model,
)
from abc_harness.agent.secrets import DEFAULT_ENV_FILE, Secrets
from abc_harness.execution.export import ExportError, export_task
from abc_harness.execution.figures import PLOT_IMAGE
from abc_harness.execution.limits import DEFAULT_LLM_CALL_LIMIT, DEFAULT_TIME_LIMIT_SECONDS, Budget
from abc_harness.execution.runner import DockerRunner, build_image
from abc_harness.execution.task import TaskResult, run_task
from abc_harness.execution.trace import summarize_trace
from abc_harness.interfaces.chat import ModelControl, run_chat, terminal_reader
from abc_harness.interfaces.console import Console, task_summary
from abc_harness.literature.pdf import PARSER_IMAGE
from abc_harness.planning.plan import Plan, PlanError, load_plan
from abc_harness.simulators import SIMULATORS, SimulatorError, get_simulator

Read = Callable[[str], str]
Write = Callable[[str], None]


S2_KEY = "SEMANTIC_SCHOLAR_API_KEY"  # optional; without it literature search uses OpenAlex only
PDF_PARSER = "pdf-parser"
PLOT = "plot"
# Images that are not simulators: name for --only -> (Docker build context, tag).
TOOL_IMAGES = {
    PDF_PARSER: (Path(__file__).resolve().parents[3] / "docker" / "mineru", PARSER_IMAGE),
    PLOT: (Path(__file__).resolve().parents[3] / "docker" / "plot", PLOT_IMAGE),
}

DEFAULT_LIBRARY_DIR = Path("papers")  # the researcher's local papers, read on demand


def prompt_decision(
    plan: Plan, read: Read | None = None, write: Write = print, allow_revise: bool = False
) -> tuple[str, str]:
    """Show the plan and ask the researcher to decide.

    An empty answer (Enter) approves. End of input or an unreadable terminal
    counts as a rejection, so a closed terminal never starts a run.
    """
    read = read or input
    choices = "approve/revise/reject" if allow_revise else "approve/reject"
    shown = choices.replace("approve", "approve(default)", 1)
    write(plan.render())
    write("")
    while True:
        try:
            answer = read(f"Approve this plan? [{shown}]: ").strip().lower()
        except (EOFError, OSError):
            return "reject", "no answer (input closed)"
        if answer in ("", "approve", "a", "yes", "y"):
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
    build = image_sub.add_parser("build", help="build the execution image of each simulator and the tool images")
    build.add_argument("--only", default="all", choices=["all", *sorted(SIMULATORS), *TOOL_IMAGES],
                       help="build one image instead of all")  # fmt: skip

    def task_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--runs-dir", type=Path, default=Path("runs"), help="where artifact directories go")
        p.add_argument("--time-limit-seconds", type=float, default=DEFAULT_TIME_LIMIT_SECONDS,
                       help="active runtime limit per task (default: 7200)")  # fmt: skip
        p.add_argument("--quiet", action="store_true",
                       help="hide live progress: the status line and the line kept for each tool call")  # fmt: skip

    run = sub.add_parser("run", help="review a plan file (TOML or plan.json) and run it after approval")
    run.add_argument("plan", type=Path)
    task_options(run)

    def agent_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--model", default=DEFAULT_MODEL)
        p.add_argument("--effort", default=DEFAULT_EFFORT, choices=EFFORTS)
        p.add_argument("--llm-call-limit", type=int, default=DEFAULT_LLM_CALL_LIMIT, help="per task")
        p.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help="file holding API keys")
        p.add_argument("--library", type=Path, default=DEFAULT_LIBRARY_DIR, metavar="DIR",
                       help="the local library: PDFs the agent may open; name a paper in your request to have it read (default: papers)")  # fmt: skip
        task_options(p)

    ask = sub.add_parser("ask", help="describe an experiment; the agent drafts a plan for your approval")
    ask.add_argument("question", help="the research question, in any language")
    agent_options(ask)
    chat = sub.add_parser("chat", help="a conversation with the agent; each request runs as its own task")
    agent_options(chat)

    trace = sub.add_parser("trace", help="inspect task traces")
    trace_sub = trace.add_subparsers(dest="trace_command", required=True)
    export = sub.add_parser("export", help="package a task's modified simulator source")
    export.add_argument("task", help="runs/<task_id>, or a task ID under --runs-dir")
    export.add_argument("--runs-dir", type=Path, default=Path("runs"))
    summary = trace_sub.add_parser("summary", help="summarize model calls, tokens, tools, and errors")
    summary.add_argument("task_dir", type=Path, help="runs/<task_id>")
    check = trace_sub.add_parser("check", help="verify execution order and reported metrics from saved artifacts")
    check.add_argument("task_dir", type=Path, help="runs/<task_id>")
    return parser


def _chat(
    args: argparse.Namespace, model: Any, literature: Any, redact: Callable[[str], str], key: Callable[[str], Any]
) -> int:
    from abc_harness.agent.session import ChatSession

    read = terminal_reader(args.runs_dir / ".chat_history")
    runner = DockerRunner()
    console = None if args.quiet else Console()
    current = {"model": model}

    def switch(name: str, effort: str | None = None) -> str | None:
        try:
            current["model"] = make_model(name, effort or current["model"].effort, key)
        except ModelUnavailable as e:
            return str(e)
        return None

    def available() -> list[str]:
        return [name if key(spec.provider.key_name) else f"{name} (needs {spec.provider.key_name} in .env)"
                for name, spec in MODELS.items()]  # fmt: skip

    def turn(session: ChatSession, text: str) -> Any:
        try:
            return _turn(session, text)
        finally:
            if console:
                console.idle()  # a stopped task must not leave the status line over the prompt

    def _turn(session: ChatSession, text: str) -> Any:
        return session.run_turn(
            text, current["model"], runner,
            lambda question: prompt_answer(question, read=read),
            lambda plan: prompt_decision(plan, read=read, allow_revise=True),
            budget=lambda: Budget(time_limit_seconds=args.time_limit_seconds, llm_call_limit=args.llm_call_limit),
            literature=literature, redact=redact, on_event=console, on_start=_announce, library_dir=args.library,
        )  # fmt: skip

    print(f"ABC Harness chat with {model.name}.")
    models = ModelControl(lambda: current["model"].name, switch, available,
                          effort=lambda: current["model"].effort,
                          set_effort=lambda level: switch(current["model"].name, level))
    return run_chat(lambda: ChatSession(args.runs_dir), turn, read, show_answers=args.quiet,
                    models=models)  # fmt: skip


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
        names = [*sorted(SIMULATORS), *TOOL_IMAGES] if args.only == "all" else [args.only]
        for name in names:
            if name in TOOL_IMAGES:
                context, tag = TOOL_IMAGES[name]
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
        if args.trace_command == "check":
            from abc_harness.execution.trace_check import check_task

            verdict, lines = check_task(args.task_dir)
            console = Console()
            for line in lines:
                console.print_line(line)
            return verdict
        print(json.dumps(summarize_trace(args.task_dir / "trace.jsonl"), indent=2, ensure_ascii=False))
        return 0

    if args.command in ("ask", "chat"):
        from abc_harness.agent.loop import run_agent_task
        from abc_harness.literature import HttpFetcher, Literature

        secrets = Secrets.load(args.env_file, names=(*API_KEY_NAMES, S2_KEY))

        def key(name: str) -> str | None:
            return secrets.get(name) if secrets.has(name) else None

        try:
            model = make_model(args.model, args.effort, key)
        except ModelUnavailable as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        literature = Literature(HttpFetcher(), secrets.get(S2_KEY) if secrets.has(S2_KEY) else None)
        if args.command == "chat":
            return _chat(args, model, literature, secrets.redact, key)
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
            library_dir=args.library,
            on_event=None if args.quiet else Console(),
        )
        summary = (result.artifact_dir / "report.md").read_text(encoding="utf-8")
        if args.quiet and "## Agent summary" in summary:  # otherwise the live output showed it already
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

