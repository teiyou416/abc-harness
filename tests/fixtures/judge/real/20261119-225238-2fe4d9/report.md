# Report (trimmed to the sections the judge reads)

## Planned versus completed runs

| Configuration | Planned | Completed | Not completed |
|---|---|---|---|
| small-a10 | 5 | 5 | - |
| small-a20 | 5 | 5 | - |
| small-a30 | 5 | 5 | - |
| small-a40 | 5 | 5 | - |
| ca-small-a10 | 5 | 5 | - |
| ca-small-a20 | 5 | 5 | - |
| ca-small-a30 | 5 | 5 | - |
| ca-small-a40 | 5 | 5 | - |

## Results

Each value is the mean over completed runs, with the sample standard deviation and the number of runs. Built-in metric definitions are in `src/abc_harness/simulators/blocksim.py`.

Custom metrics, defined by this plan and computed by the agent-written code (each run's `ABC_METRIC <name>=<value>` line in `raw/<run_id>/stdout.txt`):

- `attacker_revenue_share`: 実行終了時に正直マイナーの多数が保持するコンセンサスチェーン上の、攻撃者プール（HASH_POWERS の最後の要素のマイナー）が採掘したブロック数 / そのチェーンの全ブロック数（ジェネシスを除く）。攻撃無効（hasTrans=false）の実行では最後のマイナーを正直マイナーとして同じ式で計算する。
- `main_chain_blocks`: 実行終了時のコンセンサスチェーン上のブロック数（ジェネシスを除く）。収益率の実効サンプル数として報告する。

| Configuration | attacker_revenue_share | main_chain_blocks | stale_rate |
|---|---|---|---|
| small-a10 | 0.0625 ± 0.0111 (n=5) | 1072.0 ± 17.2 (n=5) | 0.1085 ± 0.0100 (n=5) |
| small-a20 | 0.1425 ± 0.0069 (n=5) | 951.4 ± 25.0 (n=5) | 0.2107 ± 0.0104 (n=5) |
| small-a30 | 0.2891 ± 0.0036 (n=5) | 832.4 ± 14.3 (n=5) | 0.3044 ± 0.0098 (n=5) |
| small-a40 | 0.5041 ± 0.0253 (n=5) | 714.4 ± 21.5 (n=5) | 0.3942 ± 0.0100 (n=5) |
| ca-small-a10 | 0.0560 ± 0.0071 (n=5) | 1053.4 ± 23.5 (n=5) | 0.1117 ± 0.0070 (n=5) |
| ca-small-a20 | 0.1101 ± 0.0065 (n=5) | 933.0 ± 18.0 (n=5) | 0.2072 ± 0.0045 (n=5) |
| ca-small-a30 | 0.1575 ± 0.0182 (n=5) | 810.0 ± 41.1 (n=5) | 0.3117 ± 0.0269 (n=5) |
| ca-small-a40 | 0.1646 ± 0.0205 (n=5) | 711.2 ± 15.0 (n=5) | 0.4013 ± 0.0115 (n=5) |

## Code changes and validation

The agent changed `Event.py`, `Models/Bitcoin/BlockCommit.py`, `Models/Bitcoin/Strategy.py`, `Statistics.py`. Full diff against the pinned revision: [changes/edits.diff](changes/edits.diff). Export the source with `uv run abc-harness export runs/20261119-225238-2fe4d9`.

Validation check: 攻撃なし（hasTrans=false、全員正直）で最後のマイナーがハッシュパワーの 40% を持つ場合、そのマイナーのメインチェーン占有率は閉形式の 0.4 になるはず（論文：“an honest miner’s revenue is proportional to its hash power”）。ブロック生成、10 秒伝播、同深度フォークの選択（規則にマイナー id の系統的偏りがないこと）、コンセンサスチェーン復元、custom metric をまとめて検証する。1200 ではなく 3000 ブロック/実行（simTime=1800000）で精度を上げ、5 シード平均の標準誤差を約 0.004 にし、許容差 0.02 を約 5σ にする。

Mean attacker_revenue_share over 5 of 5 validation runs: 0.4003; required 0.4 ± 0.02: **passed**. Runs and raw output: [validation.json](validation.json).

The agent ran 10 sandbox commands to build and test its code ([sandbox/](sandbox/)); their output is not a result. Its test files are in [workspace/scratch/](workspace/scratch/).

## Agent summary

The agent wrote this summary. Every number in it must match the Results table below,
which is computed from `results.json` and the raw output.

計画 `1d65e93b` を実行しました。**8 構成 × 5 シード = 40 実行、すべて completed（失敗・未完了なし）**。検証チェック（全員正直・40% マイナー）は平均 0.40030 で期待値 0.4 ± 0.02 に合格しています。

図 `revenue-vs-alpha`（平均±標本標準偏差、5 シード）と、論文 Figure 5 の同一 α の読み取り値（±0.010）との対照:

| α | Smallest-Hash 論文 | 本再現 | CA+Small 論文 | 本再現 |
|---|---|---|---|---|
| 0.1 | 0.070 | 0.063±0.011 | 0.070 | 0.056±0.007 |
| 0.2 | 0.175 | 0.143±0.007 | 0.150 | 0.110±0.007 |
| 0.3 | 0.325 | 0.289±0.004 | 0.260 | 0.158±0.018 |
| 0.4 | 0.550 | 0.504±0.025 | 0.400 | 0.165±0.020 |

**一致点**: 全 α で Smallest-Hash ＞ CA+Smallest-Hash。α=0.1 では両ルールとも y=α を下回り論文とほぼ同じ。Smallest-Hash が α=0.3・0.4 で y=α を上回り 0.1・0.2 で下回る（PT が 0.2〜0.3 の間）点も一致。

**不一致点**: (a) Smallest-Hash は全点で論文より低い（α=0.4 で 0.504 対 0.550）。(b) CA+Smallest-Hash は 0.056→0.165 とほぼ平坦で、論文のように α とともに 0.40 まで上昇せず、PT=0.4 は再現できていない。

**考えられる理由**: 最大の候補は伝播モデルの差。論文の SimBlock は 100 ノード間でホップごとに 10 秒かかるため自然フォークが多く、攻撃者の公開ブロックが公開鎖を追い越す機会が多い。本再現は BlockSim のブロックごと 1 回の指数分布（平均 10 秒、トポロジなし、BS-M2/BS-N1）で、フォークが稀になる。加えて本実装では同深度分岐を全正直ノードが同一規則で直ちに解決する（γ の分割がない）ため、CA がフォーク開始時に固定した判定が攻撃者に不利に働き続け、罰則が論文より強く出た可能性がある。ブロック id をハッシュ代用にしている点、1 実行 1200 ブロック（論文 100,000）で SD が 0.004〜0.025 ある点も結論の限界です。
