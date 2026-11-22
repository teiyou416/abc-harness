# Report (trimmed to the sections the judge reads)

## Planned versus completed runs

| Configuration | Planned | Completed | Not completed |
|---|---|---|---|
| Small_a010 | 5 | 0 | Small_a010__seed-1 (missing), Small_a010__seed-2 (missing), Small_a010__seed-3 (missing), Small_a010__seed-4 (missing), Small_a010__seed-5 (missing) |
| Small_a020 | 5 | 0 | Small_a020__seed-1 (missing), Small_a020__seed-2 (missing), Small_a020__seed-3 (missing), Small_a020__seed-4 (missing), Small_a020__seed-5 (missing) |
| Small_a030 | 5 | 0 | Small_a030__seed-1 (missing), Small_a030__seed-2 (missing), Small_a030__seed-3 (missing), Small_a030__seed-4 (missing), Small_a030__seed-5 (missing) |
| Small_a040 | 5 | 0 | Small_a040__seed-1 (missing), Small_a040__seed-2 (missing), Small_a040__seed-3 (missing), Small_a040__seed-4 (missing), Small_a040__seed-5 (missing) |
| CASmall_a010 | 5 | 0 | CASmall_a010__seed-1 (missing), CASmall_a010__seed-2 (missing), CASmall_a010__seed-3 (missing), CASmall_a010__seed-4 (missing), CASmall_a010__seed-5 (missing) |
| CASmall_a020 | 5 | 0 | CASmall_a020__seed-1 (missing), CASmall_a020__seed-2 (missing), CASmall_a020__seed-3 (missing), CASmall_a020__seed-4 (missing), CASmall_a020__seed-5 (missing) |
| CASmall_a030 | 5 | 0 | CASmall_a030__seed-1 (missing), CASmall_a030__seed-2 (missing), CASmall_a030__seed-3 (missing), CASmall_a030__seed-4 (missing), CASmall_a030__seed-5 (missing) |
| CASmall_a040 | 5 | 0 | CASmall_a040__seed-1 (missing), CASmall_a040__seed-2 (missing), CASmall_a040__seed-3 (missing), CASmall_a040__seed-4 (missing), CASmall_a040__seed-5 (missing) |

## Results

Each value is the mean over completed runs, with the sample standard deviation and the number of runs. Metric definitions are in `src/abc_harness/simulators/simblock.py`.

| Configuration | orphan_rate |
|---|---|
| Small_a010 | no data |
| Small_a020 | no data |
| Small_a030 | no data |
| Small_a040 | no data |
| CASmall_a010 | no data |
| CASmall_a020 | no data |
| CASmall_a030 | no data |
| CASmall_a040 | no data |

## Code changes and validation

The agent changed `main/java/simblock/block/Block.java`, `main/java/simblock/node/ForkChoice.java`, `main/java/simblock/node/StubbornAttacker.java`, `main/java/simblock/simulator/Main.java`, `main/java/simblock/task/DeliverBlockTask.java`. Full diff against the pinned revision: [changes/edits.diff](changes/edits.diff). Export the source with `uv run abc-harness export runs/20261119-215322-b7fa2b`.

Validation check: Known answer: with honest mining every miner earns revenue proportional to its hash power, so a pool with alpha=0.3 (mode 1: Smallest-Hash, pool behaves honestly, same 10 s delay as everyone) should have main-chain revenue share about 0.30 (paper Eq.1 and 'Ideally, an honest miner's revenue is proportional to its hash power'). The metric orphan_rate here is the redefined attacker revenue share.

Mean orphan_rate over 0 of 3 validation runs: no data; required 0.3 ± 0.005: **failed; no configuration was run**. Runs and raw output: [validation.json](validation.json).

The agent ran 5 sandbox commands to build and test its code ([sandbox/](sandbox/)); their output is not a result. Its test files are in [workspace/scratch/](workspace/scratch/).

## Agent summary

The agent wrote this summary. Every number in it must match the Results table below,
which is computed from `results.json` and the raw output.

本次任务没有产出任何正式结果。`run_plan` 对计划 `e75be975a3e7655144c1f74a977f09afcc53f6ea44fa18905b6ddea7f2c4f6e2` 返回失败,原因是验证检查失败(3 次验证运行完成 0 次)。8 个配置(每个 5 个种子)一次都没有跑,没有图,也没有与论文的对照表。

**失败原因:**
- 3 次验证运行的进程都正常退出(退出码 0),每次约 0.6 秒。
- harness 的解析器报错:`output did not parse: no block reached 90% of nodes; t90_ms is undefined`。
- 我的简化网络模型绕开了 SimBlock 的区块传播记录,而 harness 解析 `orphan_rate` 时需要这份记录来算 t90。
- 这是我的设计疏漏:提交计划前没有用 harness 的解析器检查这个依赖。"任务只能运行一个计划"的规则让我无法修复后重跑。

**验证运行自己打印的数字:**
- 以下数字来自 3 次验证运行的 stdout(`task/raw/validation__seed-*/stdout.txt`),不是 harness 的正式指标,只能当线索:
  - seed 1:攻击者收益占比 0.3003730410345138
  - seed 2:0.3013731510466151
  - seed 3:0.298242806708738
- 这是诚实挖矿、α=0.3、100,000 区块的情形,目标值是 0.30。
- 也就是说模型逻辑看起来没问题,是 harness 的解析卡住了。
- 我在沙箱里还试跑过 L-stubborn(单种子、100,000 区块)。这些也不是正式结果,所以我不报具体数字,也不据此下"哪些点与论文一致"的结论。

**论文依据:**
《Common Ancestor: A Composable Tie-Breaking Property to Mitigate Stubborn Mining Attacks》依据了以下几项:
- 10 秒诚实传播延迟、攻击者零延迟
- 100 个矿工、600 秒区块间隔
- 100,000 区块的终止条件
- L-stubborn 的定义
- 图 5 的读数

**如果要继续:**
需要重新开一个任务,并在代码里补上 harness 解析所需的区块传播记录,让 t90 有定义。完整的 8 个配置约 30 秒就能跑完,时间不是问题。
