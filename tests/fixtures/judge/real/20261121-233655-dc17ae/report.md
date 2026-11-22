# Report (trimmed to the sections the judge reads)

## Planned versus completed runs

| Configuration | Planned | Completed | Not completed |
|---|---|---|---|
| alpha-010 | 5 | 5 | - |
| alpha-020 | 5 | 5 | - |
| alpha-025 | 5 | 5 | - |
| alpha-030 | 5 | 5 | - |
| alpha-033 | 5 | 5 | - |
| alpha-040 | 5 | 5 | - |

## Results

Each value is the mean over completed runs, with the sample standard deviation and the number of runs. Built-in metric definitions are in `src/abc_harness/simulators/simblock.py`.

Custom metrics, defined by this plan and computed by the agent-written code (each run's `ABC_METRIC <name>=<value>` line in `raw/<run_id>/stdout.txt`):

- `attacker_revenue_share`: blocks on the final main chain (the chain of node id 1 at the end of the run, genesis excluded) whose minter is the attacker node (id = NUM_OF_NODES), divided by the number of blocks on that chain
- `attacker_hash_share`: the attacker node's mining power divided by the sum of mining power over all nodes at simulation start

| Configuration | attacker_revenue_share | attacker_hash_share | orphan_rate | t90_ms |
|---|---|---|---|---|
| alpha-010 | 0.0288 ± 0.0089 (n=5) | 0.1000 ± 0.0000 (n=5) | 0.0931 ± 0.0092 (n=5) | 21411.5 ± 7520.5 (n=5) |
| alpha-020 | 0.1073 ± 0.0216 (n=5) | 0.2000 ± 0.0000 (n=5) | 0.1741 ± 0.0073 (n=5) | 48678.0 ± 18097.1 (n=5) |
| alpha-025 | 0.1719 ± 0.0102 (n=5) | 0.2500 ± 0.0000 (n=5) | 0.2101 ± 0.0087 (n=5) | 71915.5 ± 17128.7 (n=5) |
| alpha-030 | 0.2437 ± 0.0241 (n=5) | 0.3000 ± 0.0000 (n=5) | 0.2353 ± 0.0053 (n=5) | 85579.4 ± 18288.7 (n=5) |
| alpha-033 | 0.3278 ± 0.0123 (n=5) | 0.3333 ± 0.0000 (n=5) | 0.2752 ± 0.0067 (n=5) | 105062.8 ± 16838.4 (n=5) |
| alpha-040 | 0.4807 ± 0.0273 (n=5) | 0.4000 ± 0.0000 (n=5) | 0.3349 ± 0.0214 (n=5) | 126094.3 ± 27437.8 (n=5) |

## Code changes and validation

The agent changed `main/java/simblock/node/Node.java`, `main/java/simblock/simulator/Main.java`, `main/java/simblock/task/SelfishMiningTask.java`. Full diff against the pinned revision: [changes/edits.diff](changes/edits.diff). Export the source with `uv run abc-harness export runs/20261121-233655-dc17ae`.

Validation check: Known-answer check on the withholding strategy itself, at γ = 0: for α = 0.4 the optimal withholding policy earns a revenue ratio of 0.48866 (Table 1 of arXiv:2007.05614, γ = 0 row α = 0.4). Honest mining would give 0.40, which is 0.089 away, so the check fails both if the attacker never withholds and if it withholds wrongly; 5 seeds of 1500 blocks give a standard error near 0.005, well inside the tolerance.

Mean attacker_revenue_share over 5 of 5 validation runs: 0.4807; required 0.48866 ± 0.05: **passed**. Runs and raw output: [validation.json](validation.json).

The agent ran 15 sandbox commands to build and test its code ([sandbox/](sandbox/)); their output is not a result. Its test files are in [workspace/scratch/](workspace/scratch/).

## Agent summary

The agent wrote this summary. Every number in it must match the Results table below,
which is computed from `results.json` and the raw output.

计划 `08808fc0…72ca` 已执行完毕：6 组 α × 5 个种子 = 30 次运行全部完成，无失败/超时；验证检查通过（均値 0.4807 vs 已知解 0.48866，容差 0.05）。

**结果**（attacker 主链区块占比，均值 ± 样本标准差，5 种子）：

| α（实际哈希占比） | 收益占比 | 孤块率 | t90 |
|---|---|---|---|
| 0.1000 | 0.0288 ± 0.0089 | 9.3% | 21.4 s |
| 0.2000 | 0.1073 ± 0.0216 | 17.4% | 48.7 s |
| 0.2500 | 0.1719 ± 0.0102 | 21.0% | 71.9 s |
| 0.3000 | 0.2437 ± 0.0241 | 23.5% | 85.6 s |
| 0.3333 | 0.3278 ± 0.0123 | 27.5% | 105.1 s |
| 0.4000 | 0.4807 ± 0.0273 | 33.5% | 126.1 s |

只有 α=0.40 时收益超过哈希占比（0.481 > 0.400），α≈1/3 处基本持平，更低 α 明显亏损——与 γ=0 下只有 α 超过 1/3 才获利的结论一致。α=0.40 与 1/3 两点分别落在 MDP 论文 γ=0 最优收益 0.48866 与 0.33705 附近。孤块率随 α 单调上升（9%→34%），t90 也从 21 s 涨到 126 s。

**依据的论文**：*Simulating a Blockchain Network with SimBlock*（仿真器能力）；*Efficient MDP Analysis for Selfish-Mining in Blockchains*（γ=0 参攷值与验证）；本地 *Common Ancestor* 论文（SimBlock 设置、α 与收益占比定义）。

**局限**：SimBlock 平局不切换分叉（等价 γ=0）；攻击者是单个节点而非矿池；无区块奖励/手续费，只能用主链区块占比代替收益；默认区域延迟（攻击者无传播优势）；每轮 1500 个区块、5 个种子。

**保存位置**：代码 `task/workspace/edited/main/java/simblock/`（`Node.java`、`task/SelfishMiningTask.java`、`simulator/Main.java`）；原始结果 `task/raw/<run_id>/`；图片 `task/figures/revenue-vs-alpha.png/.svg` 与 `orphan-rate-vs-alpha.png/.svg`（另附绘图脚本）。
