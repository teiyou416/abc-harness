# ABC Harness

ABC Harness turns a researcher's question into a reproducible blockchain simulation. From a local CLI, the researcher describes an idea, reviews the proposed experiment, and approves it. The agent then runs the experiment and returns a report linked to the underlying data.

The first release supports idea-driven experiments with [SimBlock](https://github.com/dsg-titech/simblock) and the Bitcoin model of [BlockSim](https://github.com/maher243/BlockSim). [architecture.md](architecture.md) describes the system as built and which parts of the original design sketch the first release implements. [AGENTS.md](../AGENTS.md) defines the rules for changing this repository, and the [development plan](development-plan.md) defines the milestone order.

Terms such as task, plan version, simulation run, and citation are defined in the [glossary](glossary.md).

## What a researcher can do

1. **Describe an experiment.** Enter a question in natural language. The agent identifies the comparison, the variable to change, and the metric to measure. It asks for clarification when a missing detail would change the meaning of the result.
2. **Review the evidence.** When the plan needs a reference, the agent searches configured academic indexes and conference proceedings first. It broadens the search when those sources are insufficient. The plan links each cited paper to the assumption, parameter, or metric it supports.
3. **Approve a plan.** The plan names the simulator, explains why it fits, and lists the baseline, parameters, repetitions, seeds, metrics, permitted edits, and the validation check for any new code. The researcher can approve, request changes, or reject it through the CLI.
4. **Inspect the result.** The agent executes the approved plan, checks which simulation runs completed, and reports measurements with links to the raw output. When a simulator cannot represent an assumption, the agent explains the limitation before execution. On request, the researcher can export the modified simulator source.

## MVP boundaries

- Use one agent loop and a local CLI. The first release supports one cloud model provider behind a thin client interface; the researcher supplies their own API key in `.env`, which also holds any other external service key.
- Run the harness on the researcher's Mac. The initial target is an Apple M5 with 32 GB of memory. Simulators run in a local Docker container (see [Execution environment](#execution-environment)).
- Apply two hard limits to each task: **30 minutes of active runtime** and **500 LLM calls**. Active runtime excludes time spent waiting for the researcher; the trace records that waiting time separately. Every model call counts toward the call limit, including calls made for summarization or by any future sub-agent. Each model call, with its retries, may use only the task's remaining active time, and a response that arrives after the limit, even a final answer, leaves the task `stopped_by_limit`. Stop when either limit is reached and preserve partial results.
- Use the Human Interaction tool for clarification and plan approval. Bind approval to the displayed plan version.
- Limit writes to the task workspace and the files explicitly permitted in the approved plan.
- Keep the first release focused on literature-assisted experiment planning and execution. Full paper reproduction, additional simulators, a web interface, and sub-agents are future work.

## Simulator selection

Each supported simulator has a capability card in the repository. A card lists what the simulator models, which parameters can be changed and how, which outputs and metrics it produces, known limitations, and the pinned revision. The plan must justify the chosen simulator by citing entries from the cards. When neither simulator can represent the experiment, even with permitted edits, the agent names the missing capability and stops before execution.

## Approval lifecycle

- Before approval, the agent may only read files, search literature, and ask the researcher questions.
- The researcher can approve, request changes with comments, or reject. A change request produces a new plan version that needs its own approval. A rejection ends the task without starting any simulator container.
- The harness writes each decision to the artifact directory with the plan hash and version. The runner and sandbox exec refuse to start unless an approval for the current plan version exists.
- A change to the simulator, parameters, metrics, permitted edits, validation check, or execution image requires a new plan version and fresh approval. Before the researcher sees a plan, the harness writes the execution image's ID into the plan's `execution_image` field, so the plan version covers the image. The agent cannot set this field. The runner starts only that image ID; if it no longer exists, the harness refuses to run and a new plan version is needed.
- Retrying one simulation run once after a transient failure, with an unchanged configuration, does not require new approval. The trace records the retry.

## Permitted edits

- **Parameters.** The harness applies parameter values from the approved plan to the task workspace. The agent does not edit parameter files directly.
- **New or modified code.** When a simulator lacks a required capability, such as a selfish mining strategy, the plan lists the files the agent may create or change, describes the intended behavior, and states a deterministic validation check. For selfish mining, the check compares the simulated revenue share against the closed-form result of Eyal and Sirer (2014) within a stated tolerance.
- Approval covers the scope of the edit, not a specific diff. After approval, the agent writes, builds, and tests the code in the task workspace. If the validation check passes, the experiment proceeds without another review. If it fails, the task stops and the report explains why. The agent cannot relax the validation check without a new plan version.
- The artifact directory always contains the full diff against the pinned simulator revision. `abc-harness export <task_id>` packages the modified source for the researcher.

## Execution environment

Simulators run in a prebuilt Docker image with pinned simulator revisions, no network access, and no API key. The harness and model client stay on the host. [architecture.md](architecture.md#execution-environment) describes the mechanism.

## Literature sources

- The first search round covers the venues FC, AFT, and IEEE ICBC. It uses Semantic Scholar when the researcher configures its API key in `.env`, and OpenAlex otherwise. When those venues give nothing relevant, the agent broadens the search to all venues and preprints (OpenAlex, plus Semantic Scholar with a key). More venues are added to the first round over time.
- DBLP is not used: it answers automated requests with a bot check (see [gotchas](context/gotchas.md)). IEEE Xplore may be added when the researcher configures an API key.
- The agent can read the full text of papers that have an arXiv version, through arXiv's HTML rendering, with tables as text. It can view their figures as images; figures in SVG and papers without an arXiv version are not viewable. Other papers are available by abstract only.
- A plan cites a paper with the parameter, assumption, or metric it supports and either a quote copied from the paper or a figure reading. The harness accepts a citation only if the paper came from a search in the same task, and its quote appears verbatim in the abstract or saved full text, or its figure reading names a figure the agent viewed in the task and states an uncertainty. Citations are part of the plan, so the approval covers them, and the review marks figure readings as approximate.
- The artifact directory keeps every search, found paper, figure list, and viewed figure in `literature.json`, and each full text and viewed figure image in `papers/`. The report lists each citation with the place the harness found its quote, or, for a figure reading, the image it was read from and a note that it is approximate and not checked against text.

## Run and task status

- Each simulation run ends as `completed`, `failed`, `timeout`, or `missing`. A run is `completed` when the simulator exits with status 0 and its expected output parses. A planned run that never started is `missing`.
- Each task ends as `completed`, `partial`, `stopped_by_limit`, `rejected`, `not_executed`, or `failed`. A task is `completed` only when every planned simulation run completed and any validation check passed. A task is `not_executed` when the agent ends without running a plan, for example because no simulator can represent the question.
- The harness writes the report and manifest for every status, including partial and stopped tasks.

## What each task saves

Give each task an ID and an artifact directory. Save the approved plan and all decisions, cited sources, simulator revisions and image digest, configuration, code changes, validation results, random seeds where available, raw output, and a short report. Include enough information to rerun the experiment.

Append events to `trace.jsonl` as work happens. Record model and tool calls, active and waiting time, errors, and the final stop reason. Record token usage when the provider supplies it and label cost estimates as estimates.

## Acceptance criteria

| Capability | How to verify it |
|---|---|
| Simulator integration | Run one real example with each supported simulator. Record its revision, command, configuration, and output. |
| Literature retrieval | Give the agent a question that needs a reference without supplying a paper. Verify that it finds a relevant source and uses it to justify a specific choice in the plan. |
| Simulator selection | Verify that the agent explains its choice using the capabilities required by the experiment. If neither simulator fits, it identifies the missing capability. |
| Plan approval | Approving a plan allows the corresponding run to start. Rejecting it starts no simulator container. Revising it requires approval of the new version. |
| Permitted edits | Writing outside the permitted files is refused. Agent-written code that fails its validation check stops the task, and the report explains why. |
| Result verification | Match planned configurations and repetitions against completed runs. Recalculate a reported metric from raw output. A deliberately omitted run must appear as missing in the report. |
| Controlled stopping | Exercise the time and call limits using smaller test budgets. Verify that the harness stops, removes active containers, and retains the trace and available results. |

## Delivery order

The [development plan](development-plan.md) lists the milestones, their demonstrations, and their acceptance checks. In short: first run an ordinary SimBlock example from plan approval to a checkable result, then add the agent loop, BlockSim and simulator selection, literature retrieval, and agent-written code. The MVP demonstration compares honest mining and selfish mining across mining-power shares, measuring reward share. Before treating the results as validated, document the strategy reference, reward definition, baseline, and simulator assumptions. An unexpected result is a valid outcome to report.
