"""ABC Harness: approved, reproducible blockchain simulations from a local CLI."""

__version__ = "0.1.0"


def main() -> None:
    from abc_harness.cli import main as cli_main

    raise SystemExit(cli_main())
