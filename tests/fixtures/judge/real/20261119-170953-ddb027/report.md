# Report (trimmed to the sections the judge reads)

## Planned versus completed runs

| Configuration | Planned | Completed | Not completed |
|---|---|---|---|
| delay_0_42 | 5 | 5 | - |
| delay_10 | 5 | 5 | - |
| delay_30 | 5 | 5 | - |
| delay_60 | 5 | 5 | - |

## Results

Each value is the mean over completed runs, with the sample standard deviation and the number of runs. Metric definitions are in `src/abc_harness/simulators/blocksim.py`.

| Configuration | stale_rate |
|---|---|
| delay_0_42 | 0.0004 ± 0.0003 (n=5) |
| delay_10 | 0.0104 ± 0.0032 (n=5) |
| delay_30 | 0.0273 ± 0.0024 (n=5) |
| delay_60 | 0.0536 ± 0.0025 (n=5) |

## Agent summary

The agent wrote this summary. Every number in it must match the Results table below,
which is computed from `results.json` and the raw output.

**結論:** BlockSimで平均伝播遅延を0.42秒から60秒に上げると、ステール率は平均約0.036%から約5.4%に増えました。約150倍です。測った範囲では、遅延にほぼ比例して増えています。

**実行内容:** プラン版 `bece1f7b…` を実行しました。4つの設定それぞれで5シードを回し、全20回が完了しました。失敗やタイムアウトはありません。共通の条件は、シミュレーション時間100万秒（約1,667ブロック）、ブロック間隔600秒、ハッシュパワー [50, 20, 30]、取引なしです。

| Bdelay | stale_rate 平均 | 標準偏差 |
|---|---|---|
| 0.42秒 | 0.000361 | 0.000330 |
| 10秒 | 0.01045 | 0.00323 |
| 30秒 | 0.02726 | 0.00238 |
| 60秒 | 0.05364 | 0.00250 |

**読み取れること:** 伝播遅延がブロック間隔に比べて長くなるほど、同じ高さで競合するブロックが見つかる機会が増え、フォークが増えます。0.42秒では、シード間のばらつき（標準偏差）が平均とほぼ同じ大きさです。ステールがごくまれにしか起きないためで、この値はおおよその大きさとして見てください。

**限界:**
- BlockSimにはネットワークトポロジーがありません（BS-N1）。遅延は、ブロックごとに1つの指数分布の値として与えられます（BS-M2）。地域や帯域の違いは反映されていません。
- 難易度調整はモデル化されておらず（BS-N4）、マイナーは3者のみで、全員が正直にマイニングします。
- 各設定5シードと少ないため、特に低遅延の推定は不確かです。
- 文献は引用していません。0.42秒はBlockSimの上流デフォルト値で、60秒はご質問の値です。
