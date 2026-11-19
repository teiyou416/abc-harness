"""SimBlock adapter.

SimBlock reads its parameters from Java constants and seeds its single random
generator with a hard-coded value, so every simulation run gets its own source
copy with the planned constants and seed written in, and compiles it with
javac inside the execution image.

Metric definitions (also implemented independently in scripts/recompute_metric.py):

- t90_ms: for each block section in stdout, the propagation time in
  milliseconds at which ceil(0.9 * NUM_OF_NODES) nodes had received the block;
  the mean over all blocks that reached that many nodes.
- orphan_rate: the number of "Orphan" lines divided by the number of all lines
  in blockList.txt.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from abc_harness.simulators.base import SimulatorError

REPO_ROOT = Path(__file__).resolve().parents[3]
SIMBLOCK_COMMIT = "8a1285aa37b832385b0be2ae6f804885a4a7031f"

CONFIG_FILE = "main/java/simblock/settings/SimulationConfiguration.java"
MAIN_FILE = "main/java/simblock/simulator/Main.java"

# The closed set of parameters a plan may set: name -> (Java type, minimum, maximum).
PARAMS: dict[str, tuple[str, float, float]] = {
    "NUM_OF_NODES": ("int", 2, 10_000),
    "END_BLOCK_HEIGHT": ("int", 1, 100_000),
    "INTERVAL": ("long", 1, 10**12),
    "BLOCK_SIZE": ("long", 1, 10**10),
    "AVERAGE_MINING_POWER": ("long", 1, 10**15),
    "STDEV_OF_MINING_POWER": ("long", 0, 10**15),
    "CBR_USAGE_RATE": ("float", 0.0, 1.0),
    "CHURN_NODE_RATE": ("float", 0.0, 1.0),
}
# Meaning and upstream value at SIMBLOCK_COMMIT, shown to the agent.
PARAM_DOCS: dict[str, tuple[str, str]] = {
    "NUM_OF_NODES": ("number of nodes in the network", "300"),
    "END_BLOCK_HEIGHT": ("block height at which the simulation stops (required; upstream debug value)", "3"),
    "INTERVAL": ("target block interval in milliseconds", "600000"),
    "BLOCK_SIZE": ("block size in bytes", "535000"),
    "AVERAGE_MINING_POWER": ("mean mining power (hash rate) per node", "400000"),
    "STDEV_OF_MINING_POWER": ("standard deviation of mining power per node", "100000"),
    "CBR_USAGE_RATE": ("share of nodes that use compact block relay", "0.964"),
    "CHURN_NODE_RATE": ("share of nodes that are churn nodes", "0.976"),
}
CARD = Path(__file__).with_name("simblock_card.md")
# Upstream sets END_BLOCK_HEIGHT to 3 with a "TODO revert" note, so a plan
# must state the chain length it wants. t90_ms depends on NUM_OF_NODES, so a
# plan must state that too.
REQUIRED_PARAMS = ("NUM_OF_NODES", "END_BLOCK_HEIGHT")

BLOCK_HEADER = re.compile(r"^\S+@[0-9a-f]+:(\d+)$")
PROPAGATION_LINE = re.compile(r"^(\d+),(\d+)$")


class SimBlock:
    name = "simblock"
    image_tag = f"abc-harness-sim:simblock-{SIMBLOCK_COMMIT[:7]}"
    docker_context = REPO_ROOT / "docker" / "simblock"
    source_path_in_image = "/opt/simblock/simulator/src"
    revision_path_in_image = "/opt/simblock/REVISION"
    supported_metrics = ("t90_ms", "orphan_rate")

    def describe(self) -> str:
        """Return the capability card plus the parameter table generated from PARAMS."""
        rows = [
            f"| {name} | {PARAM_DOCS[name][0]} | {java_type} | {low:g} to {high:g} | {PARAM_DOCS[name][1]} |"
            for name, (java_type, low, high) in PARAMS.items()
        ]
        table = "\n".join(
            [
                "## Plan parameters",
                "",
                f"Required: {', '.join(REQUIRED_PARAMS)}. Any other name is refused.",
                "",
                "| Name | Meaning | Type | Allowed range | Upstream value |",
                "|---|---|---|---|---|",
                *rows,
            ]
        )
        return f"{CARD.read_text(encoding='utf-8')}\n{table}\n\nRevision: SimBlock {SIMBLOCK_COMMIT}\n"

    def validate_params(self, params: dict[str, Any]) -> None:
        unknown = set(params) - set(PARAMS)
        if unknown:
            raise SimulatorError(f"SimBlock does not accept parameters: {', '.join(sorted(unknown))}")
        missing = [p for p in REQUIRED_PARAMS if p not in params]
        if missing:
            raise SimulatorError(f"SimBlock plans must set: {', '.join(missing)}")
        for name, value in params.items():
            java_type, low, high = PARAMS[name]
            numeric = (int, float) if java_type == "float" else (int,)
            if isinstance(value, bool) or not isinstance(value, numeric):
                raise SimulatorError(f"{name} must be a {'number' if java_type == 'float' else 'whole number'}")
            if not low <= value <= high:
                raise SimulatorError(f"{name} must be between {low} and {high}")

    def validate_metrics(self, metrics: list[str]) -> None:
        unknown = [m for m in metrics if m not in self.supported_metrics]
        if unknown or not metrics:
            raise SimulatorError(f"SimBlock metrics must be chosen from: {', '.join(self.supported_metrics)}")

    def apply_params(self, source_dir: Path, params: dict[str, Any], seed: int) -> list[str]:
        self.validate_params(params)
        config = source_dir / CONFIG_FILE
        text = config.read_text(encoding="utf-8")
        for name, value in params.items():
            java_type = PARAMS[name][0]
            literal = f"{float(value)}f" if java_type == "float" else f"{int(value)}{'L' if java_type == 'long' else ''}"
            pattern = re.compile(rf"^(\s*public static final {java_type} {name} = )[^;]+;", re.MULTILINE)
            text = _replace_once(pattern, rf"\g<1>{literal};", text, f"{name} in {CONFIG_FILE}")
        config.write_text(text, encoding="utf-8")

        main = source_dir / MAIN_FILE
        seed_pattern = re.compile(r"^(\s*public static Random random = new Random\()\d+(\);)", re.MULTILINE)
        main_text = _replace_once(seed_pattern, rf"\g<1>{int(seed)}L\g<2>", main.read_text(encoding="utf-8"), "seed")
        main.write_text(main_text, encoding="utf-8")
        return [CONFIG_FILE, MAIN_FILE]

    def command(self) -> str:
        return (
            "set -e; rm -rf build src/dist/output; mkdir -p build src/dist/output/graph; "
            "javac -nowarn -encoding UTF-8 -d build $(find src/main/java -name '*.java'); "
            "java -cp build:src/dist/conf simblock.simulator.Main > stdout.txt 2> stderr.txt"
        )

    def raw_outputs(self) -> dict[str, str]:
        # output.json (about 9 MB per run) and graph/ only feed the SimBlock
        # visualizer, and no metric uses them, so they are not kept.
        return {
            "stdout.txt": "stdout.txt",
            "stderr.txt": "stderr.txt",
            "blockList.txt": "src/dist/output/blockList.txt",
            "static.json": "src/dist/output/static.json",
        }

    def compute_metrics(
        self, raw_dir: Path, params: dict[str, Any], metrics: Sequence[str] | None = None
    ) -> dict[str, float]:
        wanted = self.supported_metrics if metrics is None else metrics
        values: dict[str, float] = {}
        if "t90_ms" in wanted:
            t90 = block_quantile_times(raw_dir / "stdout.txt", 0.9, params["NUM_OF_NODES"])
            if not t90:
                raise SimulatorError("no block reached 90% of nodes; t90_ms is undefined")
            values["t90_ms"] = statistics.fmean(t90)
        if "orphan_rate" in wanted:
            values["orphan_rate"] = orphan_rate(raw_dir / "blockList.txt")
        return values


def _replace_once(pattern: re.Pattern[str], replacement: str, text: str, what: str) -> str:
    new_text, count = pattern.subn(replacement, text)
    if count != 1:
        raise SimulatorError(f"expected exactly one {what}, found {count}; the SimBlock source changed")
    return new_text


def parse_propagation(stdout: Path) -> list[list[int]]:
    """Return, for each block section in stdout, the reception times in milliseconds."""
    sections: list[list[int]] = []
    current: list[int] | None = None
    for raw in stdout.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if BLOCK_HEADER.match(line):
            current = []
            sections.append(current)
        elif current is not None and (m := PROPAGATION_LINE.match(line)):
            current.append(int(m.group(2)))
        else:
            current = None
    return [s for s in sections if s]


def block_quantile_times(stdout: Path, quantile: float, num_nodes: int) -> list[int]:
    needed = math.ceil(quantile * num_nodes)
    return [sorted(times)[needed - 1] for times in parse_propagation(stdout) if len(times) >= needed]


def orphan_rate(block_list: Path) -> float:
    lines = [line for line in block_list.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise SimulatorError("blockList.txt is empty")
    return sum(1 for line in lines if line.startswith("Orphan")) / len(lines)
