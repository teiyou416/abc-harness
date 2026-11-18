# Status

**What is true right now.** Rewrite this file whole when it changes; never
append to it. Git already records the history.

**Last updated:** 2026-11-19

## What works

- M1 is done. `abc-harness run examples/simblock-baseline.toml` shows a
  hand-written plan, records the researcher's decision, and after approval runs
  10 SimBlock simulation runs in Docker in about 30 seconds. Rejection starts no
  container.
- Each task writes a report, results, manifest, trace, raw output, and source
  diffs to `runs/<task_id>/`. `scripts/recompute_metric.py` reproduces a run's
  `t90_ms` and `orphan_rate` from raw output.
- `make check` runs ruff, 32 offline tests, and the rulebook test.
  `make test-docker` runs 4 integration tests against the execution image.

## Known broken

Nothing is known broken.

## Not verified yet

- maher243/BlockSim is believed to lack a selfish mining strategy. Confirm this
  when M3 adds BlockSim.
- The harness has run only on macOS with Apple silicon and Docker Desktop.

## Deliberately not built

- The agent loop, the model client, and the LLM call limit in use (M2).
- Retrying a failed simulation run; M1 reports the run as failed instead.
- No PRs and no hosted CI: this is a personal project, and checks run locally.
- The diagram parts marked "Later" in `docs/architecture.md`.

## Next

M2 in `docs/development-plan.md`: the agent loop drafts a SimBlock plan.
