# Report (trimmed to the sections the judge reads)

## Planned versus completed runs

| Configuration | Planned | Completed | Not completed |
|---|---|---|---|
| interval_600s | 10 | 10 | - |
| interval_30s | 10 | 10 | - |

## Results

Each value is the mean over completed runs, with the sample standard deviation and the number of runs. Metric definitions are in `src/abc_harness/simulators/simblock.py`.

| Configuration | orphan_rate | t90_ms |
|---|---|---|
| interval_600s | 0.0010 ± 0.0031 (n=10) | 2183.6 ± 98.1 (n=10) |
| interval_30s | 0.0429 ± 0.0149 (n=10) | 2156.5 ± 97.8 (n=10) |

## Agent summary

The agent wrote this summary. Every number in it must match the Results table below,
which is computed from `results.json` and the raw output.

はい、30 秒間隔のほうがオーファン率ははっきり高くなりました。

**実行したもの**
- プラン `c340fb5e…f57c` は承認済みです。
- 条件は 300 ノード、100 ブロックで、ブロック間隔だけを変えました。それ以外のパラメータは SimBlock 標準のままです。
- 各条件 10 seed で、計 20 run がすべて完了しました。失敗、タイムアウト、欠損はありません。

**結果（平均 ± 標準偏差、n=10）**

| 構成 | orphan_rate | t90_ms |
|---|---|---|
| 600 秒間隔 | 0.00099 ± 0.0031 | 2183.6 ± 98.1 |
| 30 秒間隔 | 0.0429 ± 0.0149 | 2156.5 ± 97.8 |

**読み取れること**
- 30 秒間隔のオーファン率は、600 秒間隔より 1 桁以上高い値でした。
- 90% のノードにブロックが届くまでの時間（t90）は、どちらも約 2.2 秒でほぼ同じです。伝わる速さは変わらないので、間隔が短いほど、前のブロックが届く前に次のブロックが掘られて競合が起きやすくなると考えられます。これは SimBlock のフォークのモデル（SB-M4）と合っています。

**注意点**
- 1 run が 100 ブロックだけなので、オーファンの件数はもともと少ないです。特に 600 秒間隔の値は標準偏差が平均より大きく、推定精度は低めです。
- 有意差の検定はしていません。
- 想定しているのは正直なマイニングだけです（SB-N1）。ネットワークのつながり方、帯域、遅延は SimBlock の設定に固定されていて（SB-N3）、ブロックサイズも 535 KB の標準値のままです。ブロックサイズやノード数が変われば、差の大きさも変わる可能性があります。

如需中文版本，请告诉我。
