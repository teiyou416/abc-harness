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
- `make check` runs ruff and 48 offline tests. `make test-docker` runs 4
  integration tests against the execution image, and `make test-live` runs 1
  test against the Claude API.

## Known gaps

- Prompt caching does not take effect yet: `cache_read_input_tokens` stays 0.
  M2.5 addresses it.

## Known broken

Nothing is known broken.

## Not verified yet

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

M2.5 in `docs/development-plan.md`: context management with a soft limit,
compression, and `history.md`. Then M3.
