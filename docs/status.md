# Status

**What is true right now.** Rewrite this file whole when it changes; never
append to it. Git already records the history.

**Last updated:** 2026-11-19

## What works

- M1 and M3: `abc-harness run <plan>` reviews a hand-written plan and, after
  approval, runs SimBlock or BlockSim (Bitcoin model) in Docker. Reports link every metric to raw output,
  and `scripts/recompute_metric.py` reproduces them.
- M2 and M3: `abc-harness ask "<question>"` runs the agent loop against the
  Claude API. The agent reads both capability cards, chooses a simulator and
  cites both cards in its rationale, asks clarification
  questions, proposes plans for approval or revision, runs the approved
  version, and writes a summary into the report. A real run took 4 model
  calls and 70 seconds for 20 SimBlock runs.
- M2.5: the agent keeps each window under the soft limit by compressing it,
  starts the next window from harness-written task state plus a model summary,
  and archives every message in `history.md`. Prompt caching works.
- Each plan pins its execution image by ID, so an approval covers the exact
  image, and a rebuilt image needs a new plan version. Every model call, with
  its retries, may use only the task's remaining active time. A failed
  container cleanup is recorded and never stops the results and report from
  being written.
- M4 and M4.1: the agent searches OpenAlex (and Semantic Scholar with a key)
  for papers, reads arXiv full texts and tables, and views figures. A plan
  cites a quote the harness checks verbatim, or a figure reading from a figure
  viewed in the task, marked as approximate.
- M4.2: `ask --paper paper.pdf` hands the agent a PDF, parsed by MinerU in
  the PDF parser image before the agent starts. arXiv papers without HTML are
  read from their PDF. Parse time is recorded but not counted toward the
  30-minute limit; the parser has a 15-minute timeout and a cache. Table
  values from a PDF are cited only as figure readings.
- M5: after approving a plan with permitted edits, the agent changes only
  those files, builds and tests them in the sandbox, and must pass the plan's
  validation check before any configuration runs. `abc-harness export`
  packages the edited source.
- The terminal shows every model call (with the model's summarized thinking),
  tool call, plan decision, PDF parse, and simulation run as it happens, and
  prints the run statistics (time, model calls, tokens, estimated cost at list
  prices, tools, runs) at the end; `--quiet` hides the
  live part. Thinking summaries are also kept in `trace.jsonl` and
  `history.md`.
- `search_files` lets the agent find lines by regular expression, or files by
  name, in the simulator source, the example plans, and its task directory.
- After a plan runs, `make_figure` lets the agent draw static figures of the
  results: its matplotlib script runs in the plot image (results read-only,
  no network), the agent sees the PNG and can redraw, and the report shows
  each figure with its caption and script.
- `abc-harness chat` holds a conversation in the terminal: each request runs
  as its own task, the next task gets a harness-written account of the
  earlier ones and can read their files, Ctrl-C stops the running task, and
  `/tasks`, `/paper`, `/model`, `/new` manage the conversation. `/model`
  checks with the Models API that a model supports adaptive thinking and
  the effort level before the next task uses it. The command line now
  lives in `interfaces/`.
- Plans with permitted edits can define custom metrics (name and definition,
  printed by the edited code as `ABC_METRIC` lines), and built-in metrics are
  computed only when a plan asks for them. Before this, a task that redefined
  `orphan_rate` as the attacker's revenue share failed because the unused
  `t90_ms` could not be computed.
- The agent can run on DeepSeek (`deepseek-v4-pro`, `deepseek-flash`) through
  DeepSeek's Anthropic-compatible API, chosen with `--model` or `/model`; the
  model list is fixed to four current Claude models and these two. Verified
  on 2026-11-19 with real chat tasks on both models (88 `deepseek-flash` calls,
  61 `deepseek-v4-pro` calls): requests, thinking blocks, tool calls, and the
  usage fields the cost estimate reads (`cache_read_input_tokens` included)
  all work. `deepseek-v4-pro` averaged about 29 s per call, so long tasks on
  it may need a higher `--time-limit-seconds`.
- `make check` runs ruff and 218 offline tests. `make test-docker` runs 11
  integration tests against both execution images, the PDF parser image, and the plot image, and `make test-live` runs 7
  tests against the Claude API and the literature services.

## Known broken

Nothing is known broken.

## Not verified yet

- The harness has run only on macOS with Apple silicon and Docker Desktop.
- The real model has not read a supplied PDF yet; `make test-live` has no
  PDF test. MinerU quality was measured on two arXiv papers only.
- Docker Desktop's default memory (8 GB here) fits one parse (6 GB) but not a
  parse beside a simulation run (4 GB); raise it to 12 GB.
- The real model has proposed a code-changing plan, but has not yet written,
  tested, and validated code end to end; M6 does that.
- Semantic Scholar search has run only against a hand-written response; no
  key was available. Its venue names for FC, AFT, and ICBC are unchecked.

## Deliberately not built

- DBLP and IEEE Xplore search.
- BlockSim's Ethereum model.
- Retrying a failed simulation run; the report shows it as failed instead.
- Memory across tasks (Hermes-style `MEMORY.md` / `USER.md`) and `SKILL.md`.
- No PRs and no hosted CI: this is a personal project, and checks run locally.

## Next

M6 in `docs/development-plan.md`: the MVP demonstration, selfish versus honest mining.
