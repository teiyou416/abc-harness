# Status

**What is true right now.** Rewrite this file whole when it changes; never
append to it. Git already records the history.

**Last updated:** 2026-11-19

## What works

- M1: `abc-harness run <plan>` reviews a hand-written plan and, after
  approval, runs SimBlock in Docker. Reports link every metric to raw output,
  and `scripts/recompute_metric.py` reproduces them.
- M2: `abc-harness ask "<question>"` runs the agent loop against the Claude
  API. The agent reads the SimBlock capability card, asks clarification
  questions, proposes plans for approval or revision, runs the approved
  version, and writes a summary into the report. A real run took 4 model
  calls and 70 seconds for 20 SimBlock runs.
- M2.5: the agent keeps each window under the soft limit by compressing it,
  starts the next window from harness-written task state plus a model summary,
  and archives every message in `history.md`. Prompt caching works.
- `make check` runs ruff and 58 offline tests. `make test-docker` runs 4
  integration tests against the execution image, and `make test-live` runs 2
  tests against the Claude API.

## Known broken

Nothing is known broken.

## Not verified yet

- maher243/BlockSim is believed to lack a selfish mining strategy. Confirm this
  when M3 adds BlockSim.
- The harness has run only on macOS with Apple silicon and Docker Desktop.

## Deliberately not built

- Literature search (M4), BlockSim (M3), and agent-written code (M5).
- Retrying a failed simulation run; the report shows it as failed instead.
- Memory across tasks (Hermes-style `MEMORY.md` / `USER.md`) and `SKILL.md`.
- No PRs and no hosted CI: this is a personal project, and checks run locally.

## Next

M3 in `docs/development-plan.md`: BlockSim and simulator selection.
