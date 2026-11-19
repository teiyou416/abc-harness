"""Command-line interface: `image build`, `run`, `ask`, and `trace summary`."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

from abc_harness.limits import DEFAULT_LLM_CALL_LIMIT, DEFAULT_TIME_LIMIT_SECONDS, Budget
from abc_harness.model import DEFAULT_EFFORT, DEFAULT_MODEL
from abc_harness.plan import Plan, PlanError, load_plan
from abc_harness.runner import DockerRunner, build_image
from abc_harness.secrets import DEFAULT_ENV_FILE, MissingSecret, Secrets
from abc_harness.simulators import SIMULATORS, SimulatorError, get_simulator
from abc_harness.task import TaskResult, run_task
from abc_harness.trace import summarize_trace

Read = Callable[[str], str]
Write = Callable[[str], None]


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
    build = image_sub.add_parser("build", help="build the execution image for a simulator")
    build.add_argument("--simulator", default="simblock", choices=sorted(SIMULATORS))

    def task_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--runs-dir", type=Path, default=Path("runs"), help="where artifact directories go")
        p.add_argument("--time-limit-seconds", type=float, default=DEFAULT_TIME_LIMIT_SECONDS,
                       help="active runtime limit per task (default: 1800)")  # fmt: skip

    run = sub.add_parser("run", help="review a plan file (TOML or plan.json) and run it after approval")
    run.add_argument("plan", type=Path)
    task_options(run)

    ask = sub.add_parser("ask", help="describe an experiment; the agent drafts a plan for your approval")
    ask.add_argument("question", help="the research question, in any language")
    ask.add_argument("--model", default=DEFAULT_MODEL)
    ask.add_argument("--effort", default=DEFAULT_EFFORT, choices=["low", "medium", "high", "xhigh", "max"])
    ask.add_argument("--llm-call-limit", type=int, default=DEFAULT_LLM_CALL_LIMIT)
    ask.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE, help="file holding API keys")
    task_options(ask)

    trace = sub.add_parser("trace", help="inspect task traces")
    trace_sub = trace.add_subparsers(dest="trace_command", required=True)
    summary = trace_sub.add_parser("summary", help="summarize model calls, tokens, tools, and errors")
    summary.add_argument("task_dir", type=Path, help="runs/<task_id>")
    return parser


def _print_result(result: TaskResult) -> int:
    print(f"\nStatus: {result.status} ({result.stop_reason})")
    print(f"Artifacts: {result.artifact_dir}")
    if not (result.artifact_dir / "workspace").exists():
        print("No simulator was started.")
    return 0 if result.status in ("completed", "rejected", "not_executed") else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "image":
        simulator = get_simulator(args.simulator)
        image_id = build_image(simulator.docker_context, simulator.image_tag)
        print(f"Built {simulator.image_tag} ({image_id})")
        return 0

    if args.command == "trace":
        print(json.dumps(summarize_trace(args.task_dir / "trace.jsonl"), indent=2, ensure_ascii=False))
        return 0

    if args.command == "ask":
        from abc_harness.agent import run_agent_task
        from abc_harness.model import AnthropicModel

        secrets = Secrets.load(args.env_file)
        try:
            model = AnthropicModel(secrets.get("ANTHROPIC_API_KEY"), model=args.model, effort=args.effort)
        except MissingSecret as e:
            print(f"error: {e.args[0]}", file=sys.stderr)
            return 2
        result = run_agent_task(
            args.question,
            model,
            DockerRunner(get_simulator("simblock").image_tag),
            prompt_answer,
            lambda plan: prompt_decision(plan, allow_revise=True),
            runs_root=args.runs_dir,
            budget=Budget(time_limit_seconds=args.time_limit_seconds, llm_call_limit=args.llm_call_limit),
            redact=secrets.redact,
        )
        summary = (result.artifact_dir / "report.md").read_text(encoding="utf-8")
        if "## Agent summary" in summary:
            print("\n" + summary.split("## Agent summary", 1)[1].split("\n## ", 1)[0].strip())
        return _print_result(result)

    try:
        simulator = get_simulator(load_plan(args.plan).simulator)
    except (PlanError, SimulatorError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    result = run_task(
        args.plan,
        DockerRunner(simulator.image_tag),
        prompt_decision,
        runs_root=args.runs_dir,
        budget=Budget(time_limit_seconds=args.time_limit_seconds),
    )
    return _print_result(result)
