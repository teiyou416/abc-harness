"""Simulator adapters. Each adapter knows one simulator's parameters, commands, and outputs."""

from __future__ import annotations

from abc_harness.simulators.base import Simulator, SimulatorError
from abc_harness.simulators.simblock import SimBlock

SIMULATORS: dict[str, Simulator] = {"simblock": SimBlock()}


def get_simulator(name: str) -> Simulator:
    try:
        return SIMULATORS[name]
    except KeyError:
        raise SimulatorError(f"unknown simulator {name!r}; supported: {', '.join(SIMULATORS)}") from None


__all__ = ["SIMULATORS", "Simulator", "SimulatorError", "get_simulator"]
