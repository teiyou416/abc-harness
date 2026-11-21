# SimBlock capability card

Cite entries by their ID (for example `SB-M2`) when justifying a plan.

## What it models

- **SB-M1** A Bitcoin-like peer-to-peer network. Each node sits in one of six regions (North America, Europe, South America, Asia Pacific, Japan, Australia) with region-specific bandwidth and latency.
- **SB-M2** Block propagation between nodes, including compact block relay for a configurable share of nodes, and churn nodes that are online only part of the time.
- **SB-M3** Proof-of-work block production. Each node's mining power is drawn from a normal distribution; the difficulty follows the target block interval.
- **SB-M4** Forks that arise naturally when two blocks are found before the first one has propagated. Blocks that lose a fork are recorded as orphans.

## What it does not model

- **SB-N1** Mining strategies other than honest mining. Selfish mining, withholding, or any attacker behaviour needs a code change through permitted edits (see SB-S1).
- **SB-N2** Individual transactions, fees, or block rewards. Blocks have a size in bytes, not contents.
- **SB-N3** Changes to the network topology model, region bandwidths, or latencies. Those live in `NetworkConfiguration.java` and are not plan parameters.
- **SB-N4** Consensus protocols other than proof of work in the harness. Upstream has a sample proof-of-stake class, but plans cannot select it.

## Where the code is

Paths are relative to the source root, as permitted edits name them. Read them with `read_file` at `source/simblock/<path>`.

- **SB-S1** `main/java/simblock/node/Node.java`: a node's behaviour, including what it does when it mines or receives a block. A mining strategy such as withholding blocks changes this file.
- **SB-S2** `main/java/simblock/task/MiningTask.java` and `main/java/simblock/node/consensus/ProofOfWork.java`: when a node finds a block, and the proof-of-work difficulty.
- **SB-S3** `main/java/simblock/simulator/Main.java` and `main/java/simblock/settings/SimulationConfiguration.java`: the harness writes the seed and the plan parameters into these. A permitted edit of them must keep the lines it patches.
- **SB-S4** Build and test in the sandbox by compiling into scratch: `javac -nowarn -encoding UTF-8 -d classes $(find /work/src/main/java -name '*.java')`, then `java -cp classes:/work/src/dist/conf simblock.simulator.Main` from a copy that can write `dist/output`.

## Cost

- **SB-C1** One simulation run with 300 nodes and 100 blocks takes about 2 seconds in the execution image, including compilation. Run time grows with nodes times blocks. Keep a whole plan well inside the task's limits, stated in your first message, and set `run_timeout_seconds` to a few times the expected run time.

## Metrics

- **t90_ms**: for each block, the time in milliseconds until ceil(0.9 x NUM_OF_NODES) nodes have received it; the mean over all blocks that reached that many nodes.
- **orphan_rate**: orphan blocks divided by all blocks listed in `blockList.txt`.
