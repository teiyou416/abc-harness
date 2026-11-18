"""Command-line interface: `abc-harness image build` and `abc-harness run`."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from abc_harness.limits import DEFAULT_TIME_LIMIT_SECONDS, Budget
from abc_harness.plan import Plan, PlanError, load_plan
from abc_harness.runner import DockerRunner, build_image
from abc_harness.simulators import SIMULATORS, SimulatorError, get_simulator
from abc_harness.task import run_task


def prompt_decision(
    plan: Plan, read: Callable[[str], str] | None = None, write: Callable[[str], None] = print
) -> tuple[str, str]:
    """Show the plan and ask the researcher to approve or reject it.

    End of input or an unreadable terminal counts as a rejection, so a closed
    terminal never starts a run.
    """
    read = read or input
    write(plan.render())
    write("")
    while True:
        try:
            answer = read("Approve this plan? [approve/reject]: ").strip().lower()
        except (EOFError, OSError):
            return "reject", "no answer (input closed)"
        if answer in ("approve", "a", "yes", "y"):
            return "approve", ""
        if answer in ("reject", "r", "no", "n"):
            try:
                reason = read("Reason (optional): ").strip()
            except (EOFError, OSError):
                reason = ""
            return "reject", reason
        write("Please answer 'approve' or 'reject'.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="abc-harness", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    image = sub.add_parser("image", help="manage execution images")
    image_sub = image.add_subparsers(dest="image_command", required=True)
    build = image_sub.add_parser("build", help="build the execution image for a simulator")
    build.add_argument("--simulator", default="simblock", choices=sorted(SIMULATORS))

    run = sub.add_parser("run", help="review a plan file and run it after approval")
    run.add_argument("plan", type=Path, help="plan file (TOML)")
    run.add_argument("--runs-dir", type=Path, default=Path("runs"), help="where artifact directories go")
    run.add_argument(
        "--time-limit-seconds",
        type=float,
        default=DEFAULT_TIME_LIMIT_SECONDS,
        help="active runtime limit per task (default: 1800)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "image":
        simulator = get_simulator(args.simulator)
        image_id = build_image(simulator.docker_context, simulator.image_tag)
        print(f"Built {simulator.image_tag} ({image_id})")
        return 0

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
    print(f"\nStatus: {result.status} ({result.stop_reason})")
    print(f"Artifacts: {result.artifact_dir}")
    if result.status == "rejected":
        print("No simulator was started.")
    return 0 if result.status in ("completed", "rejected") else 1
