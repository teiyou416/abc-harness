"""ABC Harness: approved, reproducible blockchain simulations from a local CLI.

Layers, from high to low; a module imports only its own layer or a lower one:

    cli.py        entry point: commands and terminal prompts
    agent/        the loop, the model client, context management, prompts
    tools/        what the agent may do, one module per tool
    execution/    one task end to end: runner, limits, trace, report
    planning/     plans, versions, and the researcher's decisions
    simulators/   one adapter and capability card per simulator

docs/architecture.md ("Module map") describes every file.
"""

__version__ = "0.1.0"


def main() -> None:
    from abc_harness.cli import main as cli_main

    raise SystemExit(cli_main())
