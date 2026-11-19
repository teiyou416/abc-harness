# BlockSim capability card

Cite entries by their ID (for example `BS-M2`) when justifying a plan. The harness runs BlockSim's Bitcoin model only.

## What it models

- **BS-M1** Proof-of-work mining by a list of miners, each with its own hash power. A miner's time to find a block is exponential with a rate proportional to its share of the total hash power and to 1 / `Binterval`.
- **BS-M2** Block propagation as a single random delay per block, exponential with mean `Bdelay` seconds. There is no network topology: every miner hears every block after its own delay.
- **BS-M3** Forks and stale blocks. At the end of a run the longest chain wins; blocks off that chain count as stale.
- **BS-M4** Incentives: each main-chain block pays its miner `Breward` plus the fees of the transactions it carries. The output lists, per miner, the blocks it mined and its profit.
- **BS-M5** Transactions with sizes and fees drawn from exponential distributions, created at `Tn` per second and packed into blocks up to `Bsize`.

## What it does not model

- **BS-N1** Network topology, regions, bandwidth, or per-node reception times. There is no propagation-time metric such as t90.
- **BS-N2** Mining strategies other than honest mining. Selfish mining, withholding, or any attacker behaviour needs a code change through permitted edits (see BS-S1).
- **BS-N3** BlockSim's Ethereum model (uncles, gas). The harness does not offer it, because it fits a large mixture model on every run.
- **BS-N4** Difficulty adjustment during a run. The mean block interval stays `Binterval` for the whole run.

## Where the code is

Paths are relative to the source root, as permitted edits name them. Read them with `read_file` at `source/blocksim/<path>`.

- **BS-S1** `Models/Bitcoin/BlockCommit.py`: the block events of the Bitcoin model: a miner generates a block, receives a block, and propagates it. A mining strategy such as withholding blocks changes this file.
- **BS-S2** `Models/Bitcoin/Node.py` and `Models/Bitcoin/Consensus.py`: a miner's state (hash power, local chain) and the longest-chain fork choice.
- **BS-S3** `InputsConfig.py` and `Main.py`: the harness writes the plan parameters and the seed into these. A permitted edit of them must keep the lines it patches.
- **BS-S4** Test in the sandbox from a writable copy, because BlockSim writes its results next to its code: `cp -r /work/src run && cd run && PYTHONDONTWRITEBYTECODE=1 python Main.py`. The results land in `run/` as one `.xlsx` file; `python /opt/abc/xlsx_to_csv.py run out` turns its sheets into CSV files in `out/`.

## Cost

- **BS-C1** One simulation run of one simulated day (`simTime` = 86400) with 3 miners, 600 s blocks, and Light transactions takes about 2 seconds. Run time grows with the number of blocks (simTime / Binterval), the number of miners, and the transaction rate. Keep a whole plan well inside the 30-minute task limit.

## Metrics

- **stale_rate**: stale blocks divided by all blocks mined in the run.
- **node0_block_share**: the share of main-chain blocks (genesis excluded) mined by node 0, the first entry of `HASH_POWERS`. Compare it with node 0's share of the total hash power.
