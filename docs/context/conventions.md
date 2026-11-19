# Conventions

How changes get made in ABC Harness, for the maintainer and coding agents
alike. A rule that a test can enforce belongs in the test instead of here, and
`AGENTS.md` lists those under "What `make check` blocks".

## 1. Language

Everything written into the repo is English. Conversation with the maintainer
is in Chinese. `AGENTS.md` hard rules 1 and 2 give the details.

## 2. How much process a change needs

Process scales with how much work is thrown away if the change is wrong, and
with whether other code depends on what changes.

| Tier | Examples | What to do |
|---|---|---|
| **Direct** | a bug fix, a test, a doc fix, a new metric parser, a gotcha | Make the change and run `make check`. |
| **Short plan** | a new CLI command, a new tool, a simulator adapter | Post a 5 to 10 line plan in chat and wait for the maintainer's yes. |
| **Design change** | the agent loop, the tool-call contract, the plan schema, the approval gate, the runner, the limits, the execution image, anything that changes what a hard rule protects | Update `docs/architecture.md` or `docs/project-spec.md` first and get the maintainer's yes before writing code. |

When unsure which tier applies, ask. A question costs less than rework.

## 3. Where code goes

The package is `src/abc_harness/`. Keep it flat until a module grows past
about 400 lines. `docs/architecture.md` maps each diagram box to its module.

- A new simulator is an adapter module plus a capability card, not a change to
  the runner.
- A new agent tool is a `tool_<name>` method on `Agent` plus its schema in
  `TOOLS` (both in `agent.py`). It never calls the model or another tool
  directly, and it signals a refused request by raising `ToolError`.
- Code under `src/` never imports from `tests/`.
- Simulator source never enters this repository. The execution image fetches it
  at a pinned commit.

## 4. Testing

- Tests live in `tests/`. Plain tests run offline with no Docker and no API
  key. Tests that need Docker carry `@pytest.mark.docker`, and tests that call
  a real model or API carry `@pytest.mark.live`.
- Every behaviour change gets a test. A bug fix adds the case that would have
  caught the bug.
- **Prove the test can fail.** Break the code it guards, watch it go red, and
  put the code back. Mention what you broke in the commit body.
- Test the guards of the hard rules directly: a rejected plan starts no
  container, an unapproved plan version cannot run, a write outside the
  permitted files is refused, the API key is absent from container environments
  and traces, and each limit stops a task under a small test budget.
- Write a guard as a closed set: allow what is named and refuse the rest.
- Never assert that a string appears in source code. Import the function and
  call it.
- A test double lives in `tests/doubles/` and says in its docstring what it
  replaces.

## 5. Git, branches and commits

This is a personal project with no remote CI and no pull requests. Two
long-lived branches exist, and nobody commits to either directly.

| Branch | Holds | Receives changes from |
|---|---|---|
| `main` | the last state of `dev` that was checked and ran correctly | `dev` only |
| `dev` | integrated work in progress | work branches only |
| `feature/<name>`, `fix/<name>`, `docs/<name>` | one piece of work | direct commits |

The workflow for every change:

1. `git switch dev && git switch -c feature/<name>`.
2. Commit on the work branch. Before each commit, run `make check` and confirm
   with `git branch --show-current` that you are not on `main` or `dev`.
3. When the work is done and tested, `git switch dev && git merge --no-ff feature/<name>`,
   then delete the work branch. `--no-ff` keeps each piece of work visible as
   one merge in the history.
4. Merge `dev` into `main` only after `dev` passes `make check`, the Docker and
   live tests that the merged work touches, and the demonstration of the
   current milestone in `docs/development-plan.md`:
   `git switch main && git merge --no-ff dev`.

Commit messages and content:

- A commit message describes the code, not the conversation. The subject says
  what changed in about 70 characters or fewer. The body says why in a few
  lines.
- Make one logical change per commit. A `uv.lock` change only rides along with
  a `pyproject.toml` change.
- Never commit `runs/`, `.env`, API keys, or simulator source.

## 6. Dependencies

The runtime dependencies are the stdlib, one model provider client, and what a
milestone in `docs/development-plan.md` names. Development tools go in the
`dev` dependency group. Simulator dependencies go in the execution image, never
in `pyproject.toml`.

## 7. The rulebook: what each file holds and how it grows

| File | Holds | How it grows |
|---|---|---|
| `AGENTS.md` | routing table, definitions, hard rules, checks, commands | 100 lines at most (test). Push detail down into the files below. |
| `docs/project-spec.md` | goals, MVP boundaries, required behaviour, acceptance criteria | Changes only with a maintainer decision. |
| `docs/architecture.md` | the system, and which module is which diagram box | Present tense. Fix a sentence in the same commit that makes it false. |
| `docs/development-plan.md` | milestones in dependency order | Mark a milestone done when its acceptance passes. |
| `docs/status.md` | what works, what is broken, what is next | Rewritten whole, never appended; 120 lines at most (test). |
| `docs/context/conventions.md` | process, code layout, testing, git | Replace, never append. |
| `docs/context/gotchas.md` | traps someone already stepped on | The only append-only file. Each entry has a date and a `Retire when:` (test); 40 entries at most (test). |

A rule that can become a test becomes one: write the test, add a row to "What
`make check` blocks" in `AGENTS.md`, and delete the sentence here.
