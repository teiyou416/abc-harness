# Status

**What is true right now.** Rewrite this file whole when it changes; never
append to it. Git already records the history.

**Last updated:** 2026-11-19

## What works

- The design documents and the rulebook are in place: `AGENTS.md`,
  `docs/project-spec.md`, `docs/architecture.md`, `docs/development-plan.md`,
  and `docs/context/`.
- `make check` runs ruff, the offline tests, and the rulebook test.
- The package `abc_harness` installs. Its CLI only prints a greeting.

## Known broken

Nothing is known broken.

## Not verified yet

- SimBlock is believed to read its parameters from Java constants, so changing
  a parameter means editing source and rebuilding. Confirm this when M1 builds
  the execution image.
- maher243/BlockSim is believed to lack a selfish mining strategy. Confirm this
  when M3 adds BlockSim.

## Deliberately not built

No PRs and no hosted CI: this is a personal project, and `make check` runs
locally. The diagram parts marked "Later" in `docs/architecture.md` are also
not built.

## Next

M1 in `docs/development-plan.md`: the SimBlock execution path without an LLM.
