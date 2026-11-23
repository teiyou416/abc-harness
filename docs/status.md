# Status

**What is true right now.** Rewrite this file whole when it changes; never
append to it. Demonstration numbers and acceptance runs belong to their
milestone in [development-plan.md](development-plan.md), and git records the
history.

**Last updated:** 2026-11-21

## What works

- `abc-harness run <plan>` reviews a hand-written plan and, after approval,
  runs SimBlock or BlockSim (Bitcoin model) in Docker. [M1, M3]
- `abc-harness ask` and `abc-harness chat` run the agent: it reads both
  capability cards, chooses a simulator, asks clarification questions, and
  proposes plans; the approved version runs. [M2, M3]
- Long tasks compress their context and archive it in `history.md`. [M2.5]
- The agent searches for papers, reads arXiv full texts, views figures, and
  opens PDFs from the local library (`papers/`) on demand, parsed by
  MinerU, and keeps papers there with `save_paper`; the harness checks every
  citation.
  [M4, M4.1, M4.2]
- With permitted edits, the agent changes simulator source in the sandbox,
  defines custom metrics, and must pass a validation check before any
  configuration runs; `abc-harness export` packages the edited source. [M5]
- `make_figure` draws result figures in the plot image; `search_files`
  searches the source and task files; `chat` keeps a conversation of tasks
  with `/tasks`, `/model`, `/effort`, `/status`, `/clean`, and `/new`;
  `abc-harness clean` frees disk space without touching evidence. [M5.1]
- Twelve models: four Claude models, two DeepSeek models, three Kimi models
  (China platform; all three pass the live tool-call test, and `kimi-k3.1-pro` ran a full BlockSim task on
  2026-11-23), and three OpenAI models (not yet verified against the live API); `deepseek-flash`
  is the default. [M5.1]
- The terminal shows a status line for the current action, each tool call,
  milestones, and errors above it, and ends with run statistics, including
  an estimated cost. [M5.1]
- Per-task limits on active runtime and model calls, changed with
  `--time-limit-seconds` and `--llm-call-limit`
  ([values](project-spec.md#limits)).
- `trace check` audits saved approval, validation order, and reported metrics offline,
  and runs by itself when a task that executed a plan ends (`trace_check.json`). It also
  warns about each number in the agent's final answer that no source supports.
- `abc-harness judge` and `/judge` ask another model whether a finished task's
  answer follows from its results, on request, and keep the judgment in
  `judge.jsonl` as model-assessed advice. [M5.2]
- `make eval-judge` scores 26 gold cases (7 real tasks, 6 edited answers, 13
  constructed) and compares with labels a second agent reviewed and the
  maintainer confirmed. 2026-11-23: claude-sonnet-5-5 agreed on 23 of 24
  scored cases ($0.24), deepseek-v4-pro on 23 of 24 ($0.13), though
  deepseek-v4-pro put four bad cases at exactly the boundary score 5. [M5.2]
- `make check` runs ruff and 282 offline tests; `make test-docker` runs 11
  Docker tests and `make test-live` runs 16 tests against the model APIs and
  literature services.

## Broken or not verified

- The harness has run only on macOS with Apple silicon and Docker Desktop.
- Docker Desktop's default memory fits a PDF parse or a simulation run, not
  both at once; raise it as [Limits](project-spec.md#limits) says.
- MinerU quality was measured on two arXiv papers only.
- Semantic Scholar search has run only against a hand-written response; no
  key was available. Its venue names for FC, AFT, and ICBC are unchecked.

## Next

M6 in [development-plan.md](development-plan.md): the MVP demonstration,
selfish versus honest mining.
