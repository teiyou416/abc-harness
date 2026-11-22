# AGENTS.md: read this first

ABC Harness is a local CLI for blockchain research. A researcher describes an
experiment, reviews the proposed plan, and approves it before execution. The
harness runs the simulation and returns results the researcher can inspect and
reproduce.

This file is for everyone who changes the repo, human or coding agent. A test
caps it at 100 lines, so the detail lives in the files it points to.

## Before you... read...

| Before you | Read |
|---|---|
| start any work | [docs/status.md](docs/status.md): what works, what is broken or not verified, what is next |
| pick the next piece of work | [docs/development-plan.md](docs/development-plan.md): milestones in order |
| decide whether a feature belongs in the MVP | [docs/project-spec.md](docs/project-spec.md): scope, limits, acceptance |
| touch the loop, a tool, the approval gate, the runner or the limits | [docs/architecture.md](docs/architecture.md), then [conventions §2](docs/context/conventions.md#2-how-much-process-a-change-needs) |
| decide where new code goes | [conventions §3](docs/context/conventions.md#3-where-code-goes) |
| write or change a test | [conventions §4](docs/context/conventions.md#4-testing) |
| branch, commit or merge | [conventions §5](docs/context/conventions.md#5-git-branches-and-commits) |
| name a concept in code, docs or prompts | [docs/glossary.md](docs/glossary.md), and add the term if it is missing |
| hit something surprising | [docs/context/gotchas.md](docs/context/gotchas.md), and add it if it is missing |
| look for any other doc | [docs/README.md](docs/README.md) |

## Definitions

Project terms are defined in [docs/glossary.md](docs/glossary.md). Use them
as defined there, and add a term there before using a new one.

## Hard rules

1. **Write repository content in English.** Use English for identifiers,
   comments, docstrings, tests, CLI and log messages, prompts, configuration
   descriptions, and all Markdown. Preserve user input, quoted research
   material, and raw simulator output in their original language.
2. **Communicate with the maintainer in Chinese.** Use Chinese for questions,
   plans, progress updates, review findings, and handoffs. Keep each reply
   short: the point in a few sentences, not long sections. Keep code and
   copy-ready repository text in English, also in chat.
3. **Require approval before execution.** The agent may read files and search
   sources while drafting a plan. Before modifying experiment files or starting
   a simulation, the harness records approval for the specific plan version. A
   change to the simulator, parameters, metrics, permitted edits, validation
   check, or execution image requires a new plan version and fresh approval.
4. **Enforce limits in code.** Write only inside the task workspace. There,
   change simulator source only in the files the approved plan permits, and
   put builds and tests in `scratch/`. The harness itself may save a paper the
   agent read to the local library through `save_paper`; the agent never
   writes there.
   Enforce two limits per task, with the values in
   [Limits](docs/project-spec.md#limits): active runtime, excluding time
   spent waiting for the researcher or parsing PDFs (the PDF parser has its
   own timeout), and LLM calls. At either limit, stop active work, remove the
   task's containers, and preserve partial results.
5. **Keep credentials private.** Every API key lives in `.env` (gitignored;
   `.env.example` lists the names). Pass each key only to the client that needs
   it, never through `os.environ`. Keep keys out of containers, traces,
   artifacts, and version control.
6. **Report what actually ran.** Keep the approved plan, simulator revision,
   configuration, code changes, raw output, and `trace.jsonl` for each task.
   Every reported measurement links to its source. Label missing runs, test
   doubles, and unverified results explicitly.
7. **Run commands only inside the execution image.** Simulations go through the
   runner, and the agent's build and test commands go through sandbox exec. Do
   not add a general shell tool on the host.
8. **Fix the doc your change makes false** in the same commit.
9. **Protect `main` and `dev`.** Never commit to either directly; run
   `git branch --show-current` before committing. Cut a branch from `dev`, test
   it, and merge it into `dev`. Merge `dev` into `main` only after `dev` passes
   its checks and runs correctly.

## What `make check` blocks

There is no hosted CI. Run `make check` before every commit and merge; it
fails on:

| Blocked | Checked by |
|---|---|
| a lint error in `src/` or `tests/` | `ruff check` |
| a failing test that needs neither Docker nor an API key | `pytest` |
| this file over 100 lines, a broken relative link or heading anchor, an unindexed doc, a gotcha without `Retire when:`, an import from a higher layer, a module missing from the module map | `tests/test_rulebook.py` |

Tests marked `docker` or `live` are skipped by `make check`. Run them with
`make test-docker` and `make test-live` when a change touches the runner or the
model client.

## Commands

`make check` (lint + offline tests) · `make test` · `make test-docker` · `make test-live` · `make lint` · `make fmt`
`make image` (build every image) · `make example` / `make example-blocksim` (review and run an example plan)
`uv run abc-harness ask "<question>"` (agent drafts a plan) · `uv run abc-harness chat` (conversation, one task per request) · `uv run abc-harness trace summary runs/<task_id>` · `uv run abc-harness export runs/<task_id>` · `uv run abc-harness clean` (list removable sandbox files; `--yes` removes) · `uv run abc-harness judge runs/<task_id>`
