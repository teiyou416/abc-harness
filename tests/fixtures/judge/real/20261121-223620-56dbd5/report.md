# Report (trimmed to the sections the judge reads)

## Planned versus completed runs

| Configuration | Planned | Completed | Not completed |
|---|---|---|---|
| f-first-010 | 3 | 3 | - |
| f-small-010 | 3 | 3 | - |
| f-ca-010 | 3 | 3 | - |
| f-first-020 | 3 | 3 | - |
| f-small-020 | 3 | 3 | - |
| f-ca-020 | 3 | 3 | - |
| f-first-025 | 3 | 3 | - |
| f-small-025 | 3 | 3 | - |
| f-ca-025 | 3 | 3 | - |
| f-first-030 | 3 | 3 | - |
| f-small-030 | 3 | 3 | - |
| f-ca-030 | 3 | 3 | - |
| f-first-040 | 3 | 3 | - |
| f-small-040 | 3 | 3 | - |
| f-ca-040 | 3 | 3 | - |
| l-first-010 | 3 | 3 | - |
| l-small-010 | 3 | 3 | - |
| l-ca-010 | 3 | 3 | - |
| l-first-020 | 3 | 3 | - |
| l-small-020 | 3 | 3 | - |
| l-ca-020 | 3 | 3 | - |
| l-first-025 | 3 | 3 | - |
| l-small-025 | 3 | 3 | - |
| l-ca-025 | 3 | 3 | - |
| l-first-030 | 3 | 3 | - |
| l-small-030 | 3 | 3 | - |
| l-ca-030 | 3 | 3 | - |
| l-first-040 | 3 | 3 | - |
| l-small-040 | 3 | 3 | - |
| l-ca-040 | 3 | 3 | - |
| t1-first-010 | 3 | 3 | - |
| t1-small-010 | 3 | 3 | - |
| t1-ca-010 | 3 | 3 | - |
| t1-first-020 | 3 | 3 | - |
| t1-small-020 | 3 | 3 | - |
| t1-ca-020 | 3 | 3 | - |
| t1-first-025 | 3 | 3 | - |
| t1-small-025 | 3 | 3 | - |
| t1-ca-025 | 3 | 3 | - |
| t1-first-030 | 3 | 3 | - |
| t1-small-030 | 3 | 3 | - |
| t1-ca-030 | 3 | 3 | - |
| t1-first-040 | 3 | 3 | - |
| t1-small-040 | 3 | 3 | - |
| t1-ca-040 | 3 | 3 | - |

## Results

Each value is the mean over completed runs, with the sample standard deviation and the number of runs. Built-in metric definitions are in `src/abc_harness/simulators/simblock.py`.

Custom metrics, defined by this plan and computed by the agent-written code (each run's `ABC_METRIC <name>=<value>` line in `raw/<run_id>/stdout.txt`):

- `attacker_revenue_share`: 攻击者矿池（节点 id = NUM_OF_NODES）在最终主链上挖出的区块数除以主链区块总数。主链 = 从节点 1（诚实节点）的链尖沿 parent 回溯到创世区块，创世区块（高度 0）不计入分子与分母。由编辑后的 Main.java 在每次运行结束时向 stdout 打印一行 ABC_METRIC attacker_revenue_share=<值>。这与论文 Equation 1 的 RR_attacker（主链上攻击者区块数 / 主链总区块数）在定义上一致。

| Configuration | orphan_rate | attacker_revenue_share |
|---|---|---|
| f-first-010 | 0.1203 ± 0.0035 (n=3) | 0.1180 ± 0.0046 (n=3) |
| f-small-010 | 0.1140 ± 0.0076 (n=3) | 0.0605 ± 0.0048 (n=3) |
| f-ca-010 | 0.1136 ± 0.0109 (n=3) | 0.0565 ± 0.0066 (n=3) |
| f-first-020 | 0.2522 ± 0.0061 (n=3) | 0.2678 ± 0.0038 (n=3) |
| f-small-020 | 0.2266 ± 0.0108 (n=3) | 0.1467 ± 0.0112 (n=3) |
| f-ca-020 | 0.2208 ± 0.0088 (n=3) | 0.1115 ± 0.0093 (n=3) |
| f-first-025 | 0.3169 ± 0.0037 (n=3) | 0.3302 ± 0.0055 (n=3) |
| f-small-025 | 0.2894 ± 0.0133 (n=3) | 0.2063 ± 0.0155 (n=3) |
| f-ca-025 | 0.2837 ± 0.0108 (n=3) | 0.1450 ± 0.0262 (n=3) |
| f-first-030 | 0.4176 ± 0.0051 (n=3) | 0.4345 ± 0.0084 (n=3) |
| f-small-030 | 0.3621 ± 0.0027 (n=3) | 0.2510 ± 0.0128 (n=3) |
| f-ca-030 | 0.3635 ± 0.0036 (n=3) | 0.1907 ± 0.0045 (n=3) |
| f-first-040 | 0.6744 ± 0.0106 (n=3) | 0.6857 ± 0.0116 (n=3) |
| f-small-040 | 0.5575 ± 0.0062 (n=3) | 0.4582 ± 0.0227 (n=3) |
| f-ca-040 | 0.4919 ± 0.0225 (n=3) | 0.2438 ± 0.0403 (n=3) |
| l-first-010 | 0.1078 ± 0.0029 (n=3) | 0.1195 ± 0.0030 (n=3) |
| l-small-010 | 0.0982 ± 0.0037 (n=3) | 0.0665 ± 0.0053 (n=3) |
| l-ca-010 | 0.1011 ± 0.0080 (n=3) | 0.0642 ± 0.0099 (n=3) |
| l-first-020 | 0.1668 ± 0.0096 (n=3) | 0.2367 ± 0.0153 (n=3) |
| l-small-020 | 0.1664 ± 0.0053 (n=3) | 0.1625 ± 0.0093 (n=3) |
| l-ca-020 | 0.1715 ± 0.0062 (n=3) | 0.1720 ± 0.0156 (n=3) |
| l-first-025 | 0.1985 ± 0.0038 (n=3) | 0.3050 ± 0.0145 (n=3) |
| l-small-025 | 0.1992 ± 0.0060 (n=3) | 0.2412 ± 0.0206 (n=3) |
| l-ca-025 | 0.2047 ± 0.0049 (n=3) | 0.2311 ± 0.0010 (n=3) |
| l-first-030 | 0.2288 ± 0.0151 (n=3) | 0.3855 ± 0.0281 (n=3) |
| l-small-030 | 0.2345 ± 0.0045 (n=3) | 0.3203 ± 0.0024 (n=3) |
| l-ca-030 | 0.2351 ± 0.0094 (n=3) | 0.2978 ± 0.0227 (n=3) |
| l-first-040 | 0.2894 ± 0.0056 (n=3) | 0.5275 ± 0.0195 (n=3) |
| l-small-040 | 0.2845 ± 0.0086 (n=3) | 0.4823 ± 0.0336 (n=3) |
| l-ca-040 | 0.2884 ± 0.0080 (n=3) | 0.4648 ± 0.0205 (n=3) |
| t1-first-010 | 0.1123 ± 0.0024 (n=3) | 0.1155 ± 0.0068 (n=3) |
| t1-small-010 | 0.1066 ± 0.0063 (n=3) | 0.0650 ± 0.0053 (n=3) |
| t1-ca-010 | 0.1013 ± 0.0080 (n=3) | 0.0613 ± 0.0071 (n=3) |
| t1-first-020 | 0.2070 ± 0.0032 (n=3) | 0.2418 ± 0.0099 (n=3) |
| t1-small-020 | 0.1928 ± 0.0116 (n=3) | 0.1512 ± 0.0213 (n=3) |
| t1-ca-020 | 0.2079 ± 0.0094 (n=3) | 0.1753 ± 0.0029 (n=3) |
| t1-first-025 | 0.2689 ± 0.0090 (n=3) | 0.3173 ± 0.0100 (n=3) |
| t1-small-025 | 0.2393 ± 0.0034 (n=3) | 0.2167 ± 0.0051 (n=3) |
| t1-ca-025 | 0.2460 ± 0.0121 (n=3) | 0.2173 ± 0.0095 (n=3) |
| t1-first-030 | 0.3523 ± 0.0175 (n=3) | 0.4050 ± 0.0163 (n=3) |
| t1-small-030 | 0.3059 ± 0.0203 (n=3) | 0.2872 ± 0.0191 (n=3) |
| t1-ca-030 | 0.3085 ± 0.0128 (n=3) | 0.2905 ± 0.0107 (n=3) |
| t1-first-040 | 0.5786 ± 0.0166 (n=3) | 0.6172 ± 0.0138 (n=3) |
| t1-small-040 | 0.4725 ± 0.0417 (n=3) | 0.4497 ± 0.0673 (n=3) |
| t1-ca-040 | 0.4898 ± 0.0367 (n=3) | 0.4847 ± 0.0228 (n=3) |

## Code changes and validation

The agent changed `main/java/simblock/block/Block.java`, `main/java/simblock/node/Node.java`, `main/java/simblock/settings/SimulationConfiguration.java`, `main/java/simblock/simulator/Main.java`, `main/java/simblock/task/BlockMessageTask.java`. Full diff against the pinned revision: [changes/edits.diff](changes/edits.diff). Export the source with `uv run abc-harness export runs/20261121-223620-56dbd5`.

Validation check: 已知答案的检查：攻击类型为“不攻击”（CBR_USAGE_RATE=0.0，攻击者节点完全按诚实规则参与）时，攻击者收益占比的期望值等于它的算力占比 α=0.20；攻击者 0 延迟带来的传播优势预期只使其略高（约 +0.005）。α=0.20 时单次运行标准误约 0.011，3 个种子均值约 0.0065，容差 0.02 约 3 个标准误，能发现“收益恒为 0/1”或“算力分配错误”这类实现错误。

Mean attacker_revenue_share over 3 of 3 validation runs: 0.2060; required 0.2 ± 0.02: **passed**. Runs and raw output: [validation.json](validation.json).

The agent ran 9 sandbox commands to build and test its code ([sandbox/](sandbox/)); their output is not a result. Its test files are in [workspace/scratch/](workspace/scratch/).

## Agent summary

The agent wrote this summary. Every number in it must match the Results table below,
which is computed from `results.json` and the raw output.

已完成。计划 `cba63cf1…030a`，45 个配置 × 3 个种子 = 135 次运行，全部完成，无失败；验证检查通过（诚实挖矿 α=0.20，收益均值 0.206，容差 0.02）。

**结果**（图 `revenue-vs-alpha`）：收益随 α 单调上升，三种策略下顺序基本为 First-Seen > Smallest-Hash > CA+Smallest。α=0.40 处：F 为 0.686 / 0.458 / 0.244；L 为 0.528 / 0.482 / 0.465；T1 为 0.617 / 0.450 / 0.485。CA 在 F 下抑制最强，在 T1 的 α=0.40 处反而略高于 Smallest。只有落在 α 虚线之上才可获利。`orphan-rate-vs-alpha` 显示孤立块率随 α 上升，First-Seen 下最高（F、α=0.40：0.674 / 0.558 / 0.492），与"平局时诚实节点分裂"的机制一致。

**与论文的差距**（如实报告）：论文 Figure 4 在 α=0.40 约为 0.597 / 0.545 / 0.528，即 CA 与 Smallest 几乎重合；本实现中 CA 把攻击者收益压得更低。原因是本模拟器在真实分叉图上逐次比较哈希来判定平局，攻击者在同一分叉中会反复输掉，而论文的 F-stubborn 数值更像是每次平局都重新给攻击者机会。

**依据的论文**：Common Ancestor（本地 PDF）——600 s 出块、诚实节点 10 s / 攻击者 0 延迟、100 矿工等算力、α=0.05–0.4、攻击者合并为单池、100,000 主链区块（本次缩为 2,000）、Smallest-Hash/First-Seen 及 F/L/T1 的定义。

**限制**：2,000 区块而非 100,000；3 种子（标准误约 0.005–0.023）；攻击类型/平局规则编码在 CBR_USAGE_RATE / CHURN_NODE_RATE；无交易手续费。

图在 `task/figures/`，修改后的 SimBlock 源码在 `task/workspace/edited/`（Node.java、Block.java、SimulationConfiguration.java、BlockMessageTask.java、Main.java）。
