"""Recalculate SimBlock metrics from one simulation run's raw output.

This script deliberately imports nothing from abc_harness, so it checks the
harness's numbers instead of repeating its code. It uses only the standard
library.

Usage:
    python3 scripts/recompute_metric.py runs/<task_id>/raw/<run_id> --nodes 300

Definitions:
    t90_ms       For each block listed in stdout.txt, sort the reception times
                 and take the k-th smallest, where k = ceil(0.9 * nodes). Blocks
                 seen by fewer than k nodes are skipped. Report the mean.
    orphan_rate  Lines starting with "Orphan" in blockList.txt divided by all
                 non-empty lines.
"""

import argparse
import json
import math
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("raw_dir", type=Path, help="runs/<task_id>/raw/<run_id>")
    parser.add_argument("--nodes", type=int, required=True, help="NUM_OF_NODES used by the run")
    args = parser.parse_args()
    result = {
        "t90_ms": t90_ms(args.raw_dir / "stdout.txt", args.nodes),
        "orphan_rate": orphan_rate(args.raw_dir / "blockList.txt"),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
