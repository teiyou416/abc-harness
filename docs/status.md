# Status

**What is true right now.** Rewrite this file whole when it changes; never
append to it. Git already records the history.

**Last updated:** 2026-11-19

## What works

- M1: `abc-harness run <plan>` reviews a hand-written plan and, after
  approval, runs SimBlock in Docker. Reports link every metric to raw output,
  and `scripts/recompute_metric.py` reproduces them.
- M2 with the scripted model: `abc-harness ask "<question>"` runs the agent
  loop. The agent reads the SimBlock capability card, asks clarification
  questions, proposes plans for approval or revision, runs the approved
  version, and writes a summary into the report.
- `make check` runs ruff and 48 offline tests. `make test-docker` runs 4
  integration tests against the execution image.

## Known broken

Nothing is known broken.

## Not verified yet

- The agent loop has not run against the real Claude API, because no
  `ANTHROPIC_API_KEY` is in `.env` yet. `make test-live` skips until it is.
- maher243/BlockSim is believed to lack a selfish mining strategy. Confirm this
  when M3 adds BlockSim.
- The harness has run only on macOS with Apple silicon and Docker Desktop.

## Deliberately not built

- Literature search (M4), BlockSim (M3), and agent-written code (M5).
- Retrying a failed simulation run; the report shows it as failed instead.
- Context summarization. A task stops when its input context passes 800,000
  tokens.
- No PRs and no hosted CI: this is a personal project, and checks run locally.

## Next

Put `ANTHROPIC_API_KEY` in `.env`, run `make test-live` and one
`abc-harness ask` demonstration, then start M3.
