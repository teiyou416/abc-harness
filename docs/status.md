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
- M5: after approving a plan with permitted edits, the agent changes only
  those files, builds and tests them in the sandbox, and must pass the plan's
  validation check before any configuration runs. `abc-harness export`
  packages the edited source.
- `make check` runs ruff and 141 offline tests. `make test-docker` runs 7
  integration tests against both execution images, and `make test-live` runs 7
  tests against the Claude API and the literature services.

## Known broken

Nothing is known broken.

## Not verified yet

- The harness has run only on macOS with Apple silicon and Docker Desktop.
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
