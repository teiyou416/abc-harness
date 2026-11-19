"""BlockSim adapter (maher243/BlockSim), Bitcoin model only.

BlockSim reads its parameters from class attributes in `InputsConfig.py`, one
block per model, and never seeds its random generators. For each simulation
run the harness selects the Bitcoin model, writes the planned values into the
Bitcoin block, forces one upstream run per simulation run (repetitions come
from seeds), and seeds `random` and `numpy.random` in `Main.py`. The Ethereum
model is not offered: it fits a 39-component mixture model on every run.

Metric definitions (also implemented independently in scripts/recompute_metric.py):

- stale_rate: Stale Blocks divided by Total Blocks in SimOutput.csv.
- node0_block_share: the share of main-chain blocks (depth > 0 in Chain.csv)
  mined by node 0.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from abc_harness.simulators.base import SimulatorError

REPO_ROOT = Path(__file__).resolve().parents[3]
BLOCKSIM_COMMIT = "603361dab49101cdd820dbfd86e19536d841cbae"
CONFIG_FILE = "InputsConfig.py"
MAIN_FILE = "Main.py"
CARD = Path(__file__).with_name("blocksim_card.md")

# The closed set of plan parameters: name -> (kind, low, high, meaning, upstream value).
NUMBER, BOOL, CHOICE, HASH_LIST = "number", "bool", "choice", "hash power list"
PARAMS: dict[str, tuple[str, Any, Any, str, str]] = {
    "simTime": (NUMBER, 60, 10**7, "simulated time in seconds (required)", "10000"),
    "HASH_POWERS": (HASH_LIST, 2, 100, "hash power of each miner; node i gets entry i (required)", "[50, 20, 30]"),
    "Binterval": (NUMBER, 1, 10**5, "mean block interval in seconds", "600"),
    "Bdelay": (NUMBER, 0, 10**5, "mean block propagation delay in seconds (exponential)", "0.42"),
    "Bsize": (NUMBER, 0.001, 1000, "block size in MB", "1.0"),
    "Breward": (NUMBER, 0, 10**6, "reward for mining a block", "12.5"),
    "hasTrans": (BOOL, None, None, "model transactions and fees", "True"),
    "Ttechnique": (CHOICE, ("Light", "Full"), None, "transaction model", "Light"),
    "Tn": (NUMBER, 0, 10**5, "transactions created per second", "10"),
    "Tdelay": (NUMBER, 0, 10**5, "mean transaction propagation delay in seconds (Full model)", "5.1"),
    "Tfee": (NUMBER, 0, 10**6, "mean transaction fee", "0.000062"),
    "Tsize": (NUMBER, 1e-9, 1000, "mean transaction size in MB", "0.000546"),
}
REQUIRED_PARAMS = ("simTime", "HASH_POWERS")
BITCOIN_BLOCK = re.compile(r"(    if model == 1:\n.*?)(?=\n    ''' Input configurations for Ethereum model)", re.DOTALL)


class BlockSim:
    name = "blocksim"
    image_tag = f"abc-harness-sim:blocksim-{BLOCKSIM_COMMIT[:7]}"
    docker_context = REPO_ROOT / "docker" / "blocksim"
    source_path_in_image = "/opt/blocksim/src"
    revision_path_in_image = "/opt/blocksim/REVISION"
    supported_metrics = ("stale_rate", "node0_block_share")

    def describe(self) -> str:
        rows = []
        for name, (kind, low, high, meaning, upstream) in PARAMS.items():
            if kind == NUMBER:
                allowed = f"{low:g} to {high:g}"
            elif kind == HASH_LIST:
                allowed = f"list of {low} to {high} positive numbers"
            elif kind == CHOICE:
                allowed = " or ".join(f'"{c}"' for c in low)
            else:
                allowed = "true or false"
            rows.append(f"| {name} | {meaning} | {allowed} | {upstream} |")
        table = "\n".join([
            "## Plan parameters", "",
            f"Required: {', '.join(REQUIRED_PARAMS)}. Any other name is refused.", "",
            "| Name | Meaning | Allowed | Upstream value |", "|---|---|---|---|", *rows,
        ])  # fmt: skip
        return f"{CARD.read_text(encoding='utf-8')}\n{table}\n\nRevision: BlockSim {BLOCKSIM_COMMIT}\n"

    def validate_params(self, params: dict[str, Any]) -> None:
        unknown = set(params) - set(PARAMS)
        if unknown:
            raise SimulatorError(f"BlockSim does not accept parameters: {', '.join(sorted(unknown))}")
        missing = [p for p in REQUIRED_PARAMS if p not in params]
        if missing:
            raise SimulatorError(f"BlockSim plans must set: {', '.join(missing)}")
        for name, value in params.items():
            kind, low, high = PARAMS[name][:3]
            if kind == NUMBER:
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
                    raise SimulatorError(f"{name} must be a number between {low:g} and {high:g}")
            elif kind == BOOL and not isinstance(value, bool):
                raise SimulatorError(f"{name} must be true or false")
            elif kind == CHOICE and value not in low:
                raise SimulatorError(f"{name} must be one of {', '.join(low)}")
            elif kind == HASH_LIST and not (
                isinstance(value, list)
                and low <= len(value) <= high
                and all(not isinstance(v, bool) and isinstance(v, (int, float)) and v > 0 for v in value)
            ):
                raise SimulatorError(f"{name} must be a list of {low} to {high} positive numbers")

    def validate_metrics(self, metrics: list[str]) -> None:
        unknown = [m for m in metrics if m not in self.supported_metrics]
        if unknown or not metrics:
            raise SimulatorError(f"BlockSim metrics must be chosen from: {', '.join(self.supported_metrics)}")

    def apply_params(self, source_dir: Path, params: dict[str, Any], seed: int) -> list[str]:
        self.validate_params(params)
        config_path = source_dir / CONFIG_FILE
        text = config_path.read_text(encoding="utf-8")
        text = _replace_once(re.compile(r"^(    model = )\d+", re.MULTILINE), r"\g<1>1", text, "model selector")
        match = BITCOIN_BLOCK.search(text)
        if match is None:
            raise SimulatorError("the Bitcoin block of InputsConfig.py was not found; the BlockSim source changed")
        block = match.group(1)
        block = _set(block, "Runs", "1")
        for name, value in params.items():
            if name == "HASH_POWERS":
                nodes = ", ".join(f"Node(id={i}, hashPower={_literal(v)})" for i, v in enumerate(value))
                block = _replace_once(re.compile(r"^(        NODES = )\[Node\(.*?\)\]", re.MULTILINE | re.DOTALL),
                                      rf"\g<1>[{nodes}]", block, "NODES list")  # fmt: skip
                block = _set(block, "Nn", str(len(value)))
            else:
                block = _set(block, name, _literal(value))
        config_path.write_text(text[: match.start(1)] + block + text[match.end(1) :], encoding="utf-8")

        main_path = source_dir / MAIN_FILE
        seeded = (
            "if __name__ == '__main__':\n"
            "    import random as _abc_random\n"
            "    import numpy as _abc_numpy\n"
            f"    _abc_random.seed({int(seed)})\n"
            f"    _abc_numpy.random.seed({int(seed)})\n"
            "    main()"
        )
        main_text = main_path.read_text(encoding="utf-8")
        if main_text.count("if __name__ == '__main__':\n    main()") != 1:
            raise SimulatorError("expected exactly one main() entry point in Main.py; the BlockSim source changed")
        main_path.write_text(main_text.replace("if __name__ == '__main__':\n    main()", seeded), encoding="utf-8")
        return [CONFIG_FILE, MAIN_FILE]

    def command(self) -> str:
        return (
            "set -e; rm -rf output; cd src; "
            "PYTHONDONTWRITEBYTECODE=1 python Main.py > ../stdout.txt 2> ../stderr.txt; cd ..; "
            "python /opt/abc/xlsx_to_csv.py src output"
        )

    def raw_outputs(self) -> dict[str, str]:
        files = {"stdout.txt": "stdout.txt", "stderr.txt": "stderr.txt", "result.xlsx": "output/result.xlsx"}
        files.update({f"{s}.csv": f"output/{s}.csv" for s in ("SimOutput", "Chain", "Profit", "InputConfig")})
        return files

    def compute_metrics(self, raw_dir: Path, params: dict[str, Any]) -> dict[str, float]:
        sim = _rows(raw_dir / "SimOutput.csv")
        if len(sim) != 1:
            raise SimulatorError(f"SimOutput.csv should hold one run, found {len(sim)}")
        total = float(sim[0]["Total Blocks"])
        if total <= 0:
            raise SimulatorError("the run produced no blocks")
        chain = [r for r in _rows(raw_dir / "Chain.csv") if int(float(r["Block Depth"])) > 0]
        if not chain:
            raise SimulatorError("the main chain holds no block beyond genesis")
        node0 = sum(1 for r in chain if r["Miner ID"] and int(float(r["Miner ID"])) == 0)
        return {"stale_rate": float(sim[0]["Stale Blocks"]) / total, "node0_block_share": node0 / len(chain)}


def _literal(value: Any) -> str:
    return repr(value) if isinstance(value, (bool, str)) else (str(int(value)) if value == int(value) else repr(value))


def _set(block: str, name: str, literal: str) -> str:
    pattern = re.compile(rf"^(        {name} = )[^#\n]*?(\s*(#.*)?)$", re.MULTILINE)
    return _replace_once(pattern, rf"\g<1>{literal}\g<2>", block, f"{name} in the Bitcoin block of {CONFIG_FILE}")


def _replace_once(pattern: re.Pattern[str], replacement: str, text: str, what: str) -> str:
    new_text, count = pattern.subn(lambda m: m.expand(replacement), text)
    if count != 1:
        raise SimulatorError(f"expected exactly one {what}, found {count}; the BlockSim source changed")
    return new_text


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
