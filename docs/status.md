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
  reads supplied PDFs parsed by MinerU; the harness checks every citation.
  [M4, M4.1, M4.2]
- With permitted edits, the agent changes simulator source in the sandbox,
  defines custom metrics, and must pass a validation check before any
  configuration runs; `abc-harness export` packages the edited source. [M5]
- `make_figure` draws result figures in the plot image; `search_files`
  searches the source and task files; `chat` keeps a conversation of tasks
  with `/tasks`, `/paper`, `/model`, and `/new`. [M5.1]
- Six models: four Claude models and two DeepSeek models. [M5.1]
- The terminal shows every step live and ends with run statistics, including
  an estimated cost. [M5.1]
- Limits per task: 2 hours of active runtime and 500 LLM calls.
- `make check` runs ruff and 218 offline tests; `make test-docker` runs 11
  Docker tests and `make test-live` runs 9 tests against the model APIs and
  literature services.

## Broken or not verified

- The harness has run only on macOS with Apple silicon and Docker Desktop.
- Docker Desktop needs 12 GB of memory to parse a PDF beside a simulation
  run; its default of 8 GB fits only one of them.
- MinerU quality was measured on two arXiv papers only.
- Semantic Scholar search has run only against a hand-written response; no
  key was available. Its venue names for FC, AFT, and ICBC are unchecked.

## Next

M6 in [development-plan.md](development-plan.md): the MVP demonstration,
selfish versus honest mining.
