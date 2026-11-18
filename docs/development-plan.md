# Development plan

Milestones are ordered by dependency. Each one ends with a demonstration the researcher can run. The [project specification](project-spec.md) defines the terms, rules, and acceptance criteria referenced here.

Every milestone keeps two kinds of tests apart:

- **Test doubles** make logic tests deterministic and fast. Reports and test names must say when a result comes from a double.
- **Real components** (the model, the simulators, literature APIs) are required for the demonstration and acceptance of the milestone.

## M1: SimBlock execution path without an LLM

The plan is a hand-written file. This milestone proves the approval gate, the runner, and the artifacts before any model is involved. It is sized for a single coding agent.

**What the researcher can do.** Build the execution image, run `abc-harness run examples/simblock-baseline.yaml`, review the plan, and approve or reject it. Approval runs SimBlock and prints the artifact directory.

**Scope**

- `docker/Dockerfile` with SimBlock at a pinned commit and its JDK and Gradle dependencies. `abc-harness image build` builds it.
- CLI commands `image build` and `run`.
- Plan schema with a content-hash version. Approval records written by the harness.
- Docker runner: copy the simulator source into the task workspace, apply parameters from the plan, build, execute the planned repetitions, enforce per-run timeouts, run without network, pass only allowlisted environment variables, and remove containers by task label.
- The 30-minute active-runtime limit, configurable for tests.
- One metric parser for SimBlock output.
- `report.md`, `manifest.json` (simulator commit, image digest, commands, configuration, seeds), and `trace.jsonl`.
- README sections for setup, the exact commands used, and an independent command that recalculates the reported metric from raw output.
- `make` targets for the new commands, listed under "Commands" in `AGENTS.md`.

**Real components:** SimBlock in the execution image.

**Test doubles**

- A `FakeRunner` behind the runner interface for approval, rejection, and limit logic. These tests do not need Docker.
- A fake simulator script inside the image that writes output, sleeps, or fails. Integration tests use it to check timeout cleanup, missing runs, and that the container environment contains no API key. Mark these tests as requiring Docker.

**Demonstration:** build the image, approve the example plan, open the report, and recalculate the metric with the README command. Run again and reject the plan.

**Acceptance**

- Approving the plan runs the simulation and prints the artifact directory.
- Rejecting the plan exits without starting a container.
- Following the README reproduces the example, and at least one reported measurement can be recalculated from the saved raw output.
- All tests pass.

## M2: Agent loop plans a SimBlock experiment

**What the researcher can do.** Describe a SimBlock experiment in natural language, answer clarification questions, request changes, and approve the revised plan.

**Scope:** model client; one agent loop; tools for reading files, asking the researcher, proposing a plan, and running the approved plan; the 500-call limit; a context hard limit; `abc-harness trace summary`.

**Real components:** the model provider and SimBlock.

**Test doubles:** a scripted fake model that replays tool calls.

**Acceptance:** the "Plan approval" row of the specification; the call limit stops a task under a small test budget; the API key does not appear in the trace or artifacts.

## M3: BlockSim and simulator selection

**What the researcher can do.** Ask for an experiment that either simulator could run and read the agent's justification for its choice.

**Scope:** BlockSim in the execution image at a pinned commit; a BlockSim runner adapter and a real example; capability cards for both simulators; plan justification that cites card entries; reporting a missing capability when neither simulator fits.

**Acceptance:** the "Simulator integration" row for BlockSim and the "Simulator selection" row.

## M4: Literature retrieval

**What the researcher can do.** Ask a question that needs a reference without supplying one and see each cited source tied to a specific choice in the plan.

**Scope:** search tools for arXiv, DBLP, and Semantic Scholar; the broadening step; cited sources saved in the artifact directory.

**Test doubles:** recorded HTTP responses.

**Acceptance:** the "Literature retrieval" row.

## M5: Agent-written code in the task workspace

**What the researcher can do.** Approve a plan that adds a capability to a simulator and receive the diff, validation result, and exportable source.

**Scope:** write and edit tools restricted to the permitted files; sandbox exec inside the execution image; plan fields for permitted edits and the validation check; diff capture; `abc-harness export <task_id>`.

**Test doubles:** a scripted fake model that attempts writes inside and outside the permitted files.

**Acceptance:** the "Permitted edits" row.

## M6: MVP demonstration

**What the researcher can do.** Compare honest mining and selfish mining across mining-power shares and inspect the measured reward share.

**Scope:** the agent implements the selfish mining strategy if the chosen simulator lacks it, validates it against Eyal and Sirer (2014), and sweeps mining-power shares; the report includes the planned-versus-completed matrix and documents the strategy reference, reward definition, baseline, and simulator assumptions.

**Acceptance:** the "Result verification" and "Controlled stopping" rows, including a deliberately omitted run reported as missing and reward share recalculated from raw output.
