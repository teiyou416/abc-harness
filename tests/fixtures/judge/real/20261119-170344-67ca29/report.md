# Report (trimmed to the sections the judge reads)

## Planned versus completed runs

| Configuration | Planned | Completed | Not completed |
|---|---|---|---|
| delay_0_42 | 5 | 5 | - |
| delay_10 | 5 | 5 | - |
| delay_60 | 5 | 5 | - |

## Results

Each value is the mean over completed runs, with the sample standard deviation and the number of runs. Metric definitions are in `src/abc_harness/simulators/blocksim.py`.

| Configuration | stale_rate |
|---|---|
| delay_0_42 | 0.0004 ± 0.0003 (n=5) |
| delay_10 | 0.0104 ± 0.0032 (n=5) |
| delay_60 | 0.0536 ± 0.0025 (n=5) |

## Agent summary

The agent wrote this summary. Every number in it must match the Results table below,
which is computed from `results.json` and the raw output.

**结论：** 在 BlockSim 中，平均传播延迟从 0.42 s 增加到 60 s 后，stale block 比例从约 0.036% 升到约 5.4%，增加了两个数量级以上。

**运行情况：** 计划版本为 b880ba47…，三个配置各完成 5/5 次运行，没有失败或超时。

| Bdelay | stale_rate 均值 | 标准差 |
|---|---|---|
| 0.42 s | 0.000361 | 0.000330 |
| 10 s | 0.01045 | 0.00323 |
| 60 s | 0.05364 | 0.00250 |

**结果说明：**
- 延迟越大，stale 比例越高，三个点单调上升。
- 0.42 s 时 stale 区块极少，标准差和均值几乎一样大，所以这个值的相对误差很大，只能说明"接近零"这个量级。
- 60 s 时 5 个 seed 之间的差异小，结果比较稳定。

**设置：** 3 个诚实矿工（算力 50/20/30），平均出块间隔 600 s，每次模拟 1e6 秒（约 1667 个区块），关闭交易建模。传播延迟是均值为 Bdelay 的指数分布。

**局限：**
- BlockSim 没有网络拓扑和带宽，每个区块只有一个随机延迟（BS-M2、BS-N1）。所以这里的数值反映的是这个模型本身，不代表真实网络。
- 没有难度调整（BS-N4），只模拟了诚实挖矿。
- 每个配置只跑了 5 个 seed。
- 本计划没有引用文献。0.42 s 取自 BlockSim 的上游默认值，10 s 这个中间点是我为了看趋势自己加的。
