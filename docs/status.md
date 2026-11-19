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
- `make check` runs ruff and 74 offline tests. `make test-docker` runs 5
  integration tests against both execution images, and `make test-live` runs 5
  tests against the Claude API.

## Known broken

Nothing is known broken.

## Not verified yet

- The harness has run only on macOS with Apple silicon and Docker Desktop.

## Deliberately not built

- Literature search (M4) and agent-written code (M5).
- BlockSim's Ethereum model.
- Retrying a failed simulation run; the report shows it as failed instead.
- Memory across tasks (Hermes-style `MEMORY.md` / `USER.md`) and `SKILL.md`.
- No PRs and no hosted CI: this is a personal project, and checks run locally.

## Next

M4 in `docs/development-plan.md`: literature retrieval.
