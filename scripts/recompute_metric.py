"""Recalculate a simulation run's metrics from its raw output.

This script deliberately imports nothing from abc_harness, so it checks the
harness's numbers instead of repeating its code. It uses only the standard
library. It recognises the simulator from the files in the raw directory.

Usage:
    python3 scripts/recompute_metric.py runs/<task_id>/raw/<run_id> --nodes 300   # SimBlock
    python3 scripts/recompute_metric.py runs/<task_id>/raw/<run_id>               # BlockSim

SimBlock definitions (stdout.txt, blockList.txt):
    t90_ms             For each block listed in stdout.txt, sort the reception
                       times and take the k-th smallest, where
                       k = ceil(0.9 * nodes). Blocks seen by fewer than k nodes
                       are skipped. Report the mean.
    orphan_rate        Lines starting with "Orphan" in blockList.txt divided by
                       all non-empty lines.

BlockSim definitions (SimOutput.csv, Chain.csv):
    stale_rate         "Stale Blocks" divided by "Total Blocks".
    node0_block_share  Chain rows with "Block Depth" above 0 whose "Miner ID" is
                       0, divided by all chain rows with "Block Depth" above 0.
"""

import argparse
import csv
import json
import math
import sys
from pathlib import Path


def t90_ms(stdout_path: Path, nodes: int) -> float:
    k = math.ceil(0.9 * nodes)
    blocks, times = [], None
    for line in stdout_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        head, sep, tail = line.rpartition(":")
        if "@" in head and sep and tail.isdigit():
            times = []
            blocks.append(times)
        elif times is not None and line.count(",") == 1 and line.replace(",", "").isdigit():
            times.append(int(line.split(",")[1]))
        else:
            times = None
    per_block = [sorted(t)[k - 1] for t in blocks if len(t) >= k]
    return sum(per_block) / len(per_block)


def orphan_rate(block_list_path: Path) -> float:
    lines = [ln for ln in block_list_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return sum(ln.startswith("Orphan") for ln in lines) / len(lines)


def read_csv(path: Path) -> list:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def stale_rate(sim_output_path: Path) -> float:
    (row,) = read_csv(sim_output_path)
    return float(row["Stale Blocks"]) / float(row["Total Blocks"])


def node0_block_share(chain_path: Path) -> float:
    blocks = [r for r in read_csv(chain_path) if float(r["Block Depth"]) > 0]
    mined_by_node0 = [r for r in blocks if r["Miner ID"] != "" and float(r["Miner ID"]) == 0]
    return len(mined_by_node0) / len(blocks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("raw_dir", type=Path, help="runs/<task_id>/raw/<run_id>")
    parser.add_argument("--nodes", type=int, help="NUM_OF_NODES used by a SimBlock run")
    args = parser.parse_args()
    if (args.raw_dir / "SimOutput.csv").exists():
        result = {
            "stale_rate": stale_rate(args.raw_dir / "SimOutput.csv"),
            "node0_block_share": node0_block_share(args.raw_dir / "Chain.csv"),
        }
    elif args.nodes is None:
        sys.exit("SimBlock output needs --nodes (the run's NUM_OF_NODES)")
    else:
        result = {
            "t90_ms": t90_ms(args.raw_dir / "stdout.txt", args.nodes),
            "orphan_rate": orphan_rate(args.raw_dir / "blockList.txt"),
        }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
