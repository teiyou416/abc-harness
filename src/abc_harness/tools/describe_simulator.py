"""Return a simulator's capability card."""

from __future__ import annotations

from typing import Any

from abc_harness.simulators import SIMULATORS, SimulatorError, get_simulator
from abc_harness.tools.base import ToolContext, ToolError

SPEC: dict[str, Any] = {
    "name": "describe_simulator",
    "description": "Return a supported simulator's capability card: what it models and does not model, "
    "run cost, metrics, and the closed set of plan parameters with allowed ranges.",
    "input_schema": {
        "type": "object",
        "properties": {"simulator": {"type": "string", "enum": sorted(SIMULATORS)}},
        "required": ["simulator"],
    },
}


def run(ctx: ToolContext, args: dict[str, Any]) -> str:
    try:
        return get_simulator(str(args.get("simulator"))).describe()
    except SimulatorError as e:
        raise ToolError(str(e)) from e
