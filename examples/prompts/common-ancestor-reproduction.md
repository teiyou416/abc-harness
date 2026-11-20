# Reproducing the Common Ancestor paper's stubborn-mining experiment

Prompts for `abc-harness chat` that ask the agent to reproduce one experiment
of the Common Ancestor paper (`thesis/common_anchestor.pdf`) and draw a figure
to compare with it. The same prompts are given in Chinese, Japanese, and
English; use any one. The agent answers in the language you write in.

The first request reproduces only L-stubborn under two fork-choice rules, so
it fits in one task. The follow-up extends it to the other two attacks in a
new task of the same conversation.

## Before a live demo

- Docker Desktop is running with at least 12 GB of memory
  (`docker info --format '{{.MemTotal}}'`).
- All images are built: `uv run abc-harness image build` (SimBlock, BlockSim,
  PDF parser, plot).
- `.env` holds `ANTHROPIC_API_KEY`.
- `make check` passes.
- The paper has been parsed once before, so the parse cache makes it instant.
  If not, start the chat a few minutes early: the first parse takes 1 to 6
  minutes.
- Expect the whole first request to take 20 to 60 minutes: reading the paper,
  writing and testing the strategy code, the validation check, the runs, and
  the figure. If time is short, use the shorter scope in the note under each
  prompt.
- What to point out to the audience: the plan review (permitted edits and the
  validation check), the live thinking and tool calls, the validation result
  before any experiment runs, the figure, and `report.md` with every number
  linked to raw output.

## 中文

启动（带上论文；每个任务默认有 2 小时）：

```bash
uv run abc-harness chat --paper thesis/common_anchestor.pdf
```

第一条提示词：

```text
请复现论文 local:common-anchestor 中 L-stubborn 攻击的实验，并画图和论文对比。

范围只做这一部分：
- 攻击：L-stubborn
- 分叉规则：Smallest-Hash 和 CA+Smallest-Hash
- 攻击者算力 α：0.1、0.2、0.3、0.4，每个点 5 个随机种子
- 区块数可以比论文少，但请先在沙箱里测运行时间，保证能在时限内跑完，并在计划里说明区块数和理由

要求：
1. 先读论文里这个实验的设置和对应的结果图，计划中的关键参数要引用论文原文或读图结果。
2. 模拟器缺少的功能（L-stubborn 策略、CA 分叉规则）用 permitted edits 加进去，并设计一个有已知答案的验证检查（例如诚实挖矿时攻击者收益约等于 α），通过后再跑正式实验。攻击者收益占比请用 custom_metrics 定义成一个新指标，不要借用模拟器的内置指标。
3. 跑完后用 make_figure 画图：横轴 α，纵轴攻击者收益占比，两种规则各一条带误差棒的曲线，加 y = α 参考线。另外把论文图上同样几个点的读数和你的结果列成对照表。
4. 用中文写结论：哪些点和论文一致、哪些不一致，以及可能的原因。
```

时间不够时：把 α 改成「0.2、0.4」，种子数改成 3。

追问（同一个对话里）：

```text
现在用同样的方法，把 F-stubborn 和 T1-stubborn 也跑一遍，同样两种规则、同样的 α 和种子数，画成一张三栏对比图（每种攻击一栏）。
```

## 日本語

起動（論文を渡す。1 タスクの制限時間は既定で 2 時間）：

```bash
uv run abc-harness chat --paper thesis/common_anchestor.pdf
```

最初のプロンプト：

```text
論文 local:common-anchestor の L-stubborn 攻撃の実験を再現し、論文と比較できる図を描いてください。

範囲はこの部分だけです：
- 攻撃：L-stubborn
- フォーク選択ルール：Smallest-Hash と CA+Smallest-Hash
- 攻撃者のハッシュレート α：0.1、0.2、0.3、0.4、各点 5 つの乱数シード
- ブロック数は論文より少なくて構いませんが、まずサンドボックスで実行時間を測り、制限時間内に終わることを確認し、計画の中でブロック数とその理由を説明してください

要件：
1. まず論文のこの実験の設定と対応する結果の図を読み、計画の主要なパラメータには論文の原文または図の読み取り値を引用してください。
2. シミュレータにない機能（L-stubborn 戦略、CA フォーク選択ルール）は permitted edits で追加し、答えが分かっている検証チェック（例：正直なマイニングでは攻撃者の収益が α とほぼ等しい）を設計し、それに合格してから本実験を実行してください。攻撃者の収益の割合は custom_metrics で新しい指標として定義し、シミュレータの組み込み指標を流用しないでください。
3. 実行後、make_figure で図を描いてください：横軸 α、縦軸は攻撃者の収益の割合、2 つのルールをそれぞれエラーバー付きの曲線で示し、y = α の参照線を加えてください。さらに、論文の図の同じ点の読み取り値とあなたの結果の対照表を作ってください。
4. 結論を日本語で書いてください：どの点が論文と一致し、どの点が一致しないか、そして考えられる理由。
```

時間が足りない場合：α を「0.2、0.4」に、シード数を 3 にしてください。

続けての依頼（同じ会話の中で）：

```text
同じ方法で F-stubborn と T1-stubborn も実行してください。ルール、α、シード数は同じにして、攻撃ごとに 1 列の 3 列比較図を描いてください。
```

## English

Start (with the paper; each task has 2 hours by default):

```bash
uv run abc-harness chat --paper thesis/common_anchestor.pdf
```

First prompt:

```text
Please reproduce the L-stubborn attack experiment of the paper local:common-anchestor and draw a figure to compare with the paper.

Scope, only this part:
- Attack: L-stubborn
- Fork-choice rules: Smallest-Hash and CA+Smallest-Hash
- Attacker hash power α: 0.1, 0.2, 0.3, 0.4, with 5 random seeds per point
- You may simulate fewer blocks than the paper, but first measure the run time in the sandbox so the experiment fits in the time limit, and explain the block count and why in the plan

Requirements:
1. First read the paper's setup for this experiment and the corresponding result figure; cite the paper's text or a figure reading for each key parameter in the plan.
2. Add what the simulator lacks (the L-stubborn strategy and the CA fork-choice rule) through permitted edits, and design a validation check with a known answer (for example, under honest mining the attacker's revenue share is about α). Run the experiment only after it passes. Define the attacker's revenue share as a new metric in custom_metrics; do not reuse a built-in metric of the simulator.
3. After the runs, draw a figure with make_figure: α on the x axis, the attacker's revenue share on the y axis, one curve with error bars per rule, and a y = α reference line. Also give a table that compares your results with readings from the paper's figure at the same points.
4. Write the conclusion in English: which points agree with the paper, which do not, and possible reasons.
```

If time is short: use α of 0.2 and 0.4 and 3 seeds.

Follow-up (in the same conversation):

```text
Now run F-stubborn and T1-stubborn the same way, with the same two rules, α values, and seeds, and draw a three-panel comparison figure with one panel per attack.
```
