# ABC Harness

ABC Harness turns a researcher's question into a reproducible blockchain simulation. From a local CLI, the researcher describes an idea, reviews the proposed experiment, and approves it. The agent then runs the experiment and returns a report linked to the underlying data.

The first release supports idea-driven experiments with [SimBlock](https://github.com/dsg-titech/simblock) and the Bitcoin model of [BlockSim](https://github.com/maher243/BlockSim). [architecture.md](architecture.md) describes the system as built. [AGENTS.md](../AGENTS.md) defines the rules for changing this repository, and the [development plan](development-plan.md) defines the milestone order.

Terms such as task, plan version, simulation run, and citation are defined in the [glossary](glossary.md).

## What a researcher can do

1. **Describe an experiment.** Enter a question in natural language. The agent identifies the comparison, the variable to change, and the metric to measure. It asks for clarification when a missing detail would change the meaning of the result.
2. **Review the evidence.** When the plan needs a reference, the agent searches configured academic indexes and conference proceedings first. It broadens the search when those sources are insufficient. The plan links each cited paper to the assumption, parameter, or metric it supports.
3. **Approve a plan.** The plan names the simulator, explains why it fits, and lists the baseline, parameters, repetitions, seeds, metrics, permitted edits, and the validation check for any new code. The researcher can approve, request changes, or reject it through the CLI.
4. **Inspect the result.** The agent executes the approved plan, checks which simulation runs completed, and reports measurements with links to the raw output. When a simulator cannot represent an assumption, the agent explains the limitation before execution. On request, the researcher can export the modified simulator source.

## MVP boundaries

- Use one agent loop and a local CLI. The model client supports a fixed list of models from five providers behind one thin interface: Claude (Opus 5.5 by default, Sonnet 5.5, Haiku 5.5, Fable 5.2), DeepSeek (`deepseek-v4-pro`, `deepseek-flash`), and Kimi on Moonshot's China platform (`kimi-k3.1-pro`, `kimi-k3.1-pro-highspeed`, `kimi-k3`), Qwen on Alibaba Model Studio's Beijing region (`qwen4-max`, `qwen3.8-flash`), the latter three through their Anthropic-compatible APIs, and OpenAI (`gpt-6.2-sol`, `gpt-6.2-astra`, `gpt-6-luna`) through its Responses API, translated to the same interface. The researcher supplies each provider's API key in `.env`, which also holds any other external service key. A model that cannot see images (`deepseek-v4-pro`) cannot read figures or check its own figures; the tools say so instead of pretending.
- Run the harness on the researcher's Mac. The initial target is an Apple M5 with 32 GB of memory. Simulators run in a local Docker container (see [Execution environment](#execution-environment)).
- Apply two hard limits to each task, **active runtime** and **LLM calls**, with the values in [Limits](#limits). Active runtime excludes time spent waiting for the researcher and time spent parsing PDFs; the trace records both separately. The limit exists to stop a model that spins; a PDF parse is not model work, so it has its own timeout per PDF instead. Every model call counts toward the call limit, including calls made for summarization or by any future sub-agent. Each model call, with its retries, may use only the task's remaining active time, and a response that arrives after the limit, even a final answer, leaves the task `stopped_by_limit`. Stop when either limit is reached and preserve partial results.
- Use the Human Interaction tool for clarification and plan approval. Bind approval to the displayed plan version.
- Limit writes to the task workspace and the files explicitly permitted in the approved plan.
- Keep the first release focused on literature-assisted experiment planning and execution. Full paper reproduction, additional simulators (such as BlockEmulator), custom tools, a web interface, sub-agents, and LLM Ops beyond the trace, the run statistics, `trace check`, the on-demand [judge](#judge), and the planned model [benchmark](#benchmark) (diagnosis of failed tasks, release gates, and judged offline evaluation suites) are future work.
- Deliberately not built: DBLP and IEEE Xplore search, BlockSim's Ethereum model, automatic retry of a failed simulation run (the report shows it as failed), and memory across conversations (a `MEMORY.md` or `USER.md`) or `SKILL.md` files.

## Limits

Every number that bounds a task lives in this table; other documents name the limit and link here. The code holds the same values, and the column "Set in" says where.

| Limit | Value | Set in |
|---|---|---|
| Active runtime per task (waiting for the researcher and parsing PDFs excluded) | 2 hours; `--time-limit-seconds` changes it | `execution/limits.py` |
| LLM calls per task, summary calls included | 500; `--llm-call-limit` changes it | `execution/limits.py` |
| Output per model reply, thinking included | 65,536 tokens | `agent/model.py`, `agent/context.py` |
| Soft context limit: compress before an input this large | 106,496 tokens | `agent/context.py` |
| Hard context limit: input plus one full reply | 180,224 tokens | `agent/context.py` |
| Reply of the summary call, thinking included | 32,768 tokens | `agent/context.py` |
| Summary length | 1,500 words | `agent/prompts/compact.md` |
| One tool result in the context window | 8,192 tokens | `agent/context.py` |
| Simulation run and sandbox exec container | 2 CPUs, 4 GB of memory; each run's timeout is set by its plan | `execution/runner.py` |
| PDF parse container | 6 CPUs, 6 GB of memory, 15-minute timeout | `execution/runner.py`, `literature/pdf.py` |
| Figure script container | the simulation container's CPU and memory, 120-second timeout | `execution/figures.py` |
| Model calls per judgment (one retry for an unreadable verdict) | 2 | `agent/judge.py` |
| Output per judge reply, thinking included | 16,384 tokens | `agent/judge.py` |
| Time per judge call, retries included | 120 seconds | `agent/judge.py` |
| Docker Desktop memory | 12 GB, to parse a PDF beside a simulation run | the researcher's Docker settings |

## Simulator selection

Each supported simulator has a capability card in the repository. A card lists what the simulator models, which parameters can be changed and how, which outputs and metrics it produces, known limitations, and the pinned revision. The plan must justify the chosen simulator by citing entries from the cards. When neither simulator can represent the experiment, even with permitted edits, the agent names the missing capability and stops before execution.

## Approval lifecycle

- Before approval, the agent may only read files, search literature, and ask the researcher questions.
- The researcher can approve, request changes with comments, or reject. A change request produces a new plan version that needs its own approval. A rejection ends the task without starting any simulator container.
- The harness writes each decision to the artifact directory with the plan hash and version. The runner and sandbox exec refuse to start unless an approval for the current plan version exists.
- A change to the simulator, parameters, metrics, permitted edits, validation check, or execution image requires a new plan version and fresh approval. Before the researcher sees a plan, the harness writes the execution image's ID into the plan's `execution_image` field, so the plan version covers the image. The agent cannot set this field. The runner starts only that image ID; if it no longer exists, the harness refuses to run and a new plan version is needed.
- In a [benchmark](#benchmark), which the researcher starts and confirms once, the benchmark command approves every plan version itself. The harness records each such approval for its plan version as made by the benchmark command, never as the researcher's, so the record says no one reviewed the plan. Outside a benchmark only the researcher approves.
- Retrying one simulation run once after a transient failure, with an unchanged configuration, would not require new approval, and the trace would record the retry. The harness does not retry yet: a failed run is reported as failed.

## Permitted edits

- **Parameters.** The harness applies parameter values from the approved plan to the task workspace. The agent does not edit parameter files directly.
- **New or modified code.** When a simulator lacks a required capability, such as a selfish mining strategy, the plan lists the files the agent may create or change, describes the intended behavior, and states a deterministic validation check. For selfish mining, the check compares the simulated revenue share against the closed-form result of Eyal and Sirer (2014) within a stated tolerance.
- Approval covers the scope of the edit, not a specific diff. After approval, the agent writes, builds, and tests the code in the task workspace. If the validation check passes, the experiment proceeds without another review. If it fails, the task stops and the report explains why. The agent cannot relax the validation check without a new plan version.
- The validation check runs a stated configuration and seeds on the edited source, and passes if the mean of one plan metric lies within the stated tolerance of the expected value. The harness runs it and decides; the agent writes the code but not the verdict. It runs once, when the agent calls `run_plan`, before any configuration.
- The agent edits files only with its write tools, and only the files the approved plan permits. Its own tests and builds go to a scratch directory. At `run_plan` the harness refuses to run if any other source file differs from the original.
- A configuration can run the original source instead of the edited one, for example an honest-mining baseline next to a selfish-mining strategy.
- **Custom metrics.** When the question needs a quantity no built-in metric measures, such as the attacker's revenue share, the plan defines it: a new name and a precise definition, shown in the review. The edited source prints one `ABC_METRIC <name>=<value>` line to stdout per run, and the harness reads it from the saved raw output. The report lists custom metrics with their definitions and says the agent's code computed them. A built-in metric may not be redefined, and the agent may not change the simulator's own output files so that a built-in metric computes something else. Runs on the original source report only built-in metrics.
- Built-in metrics are computed only when the plan asks for them, so edited code that drops output one metric needs (for example the propagation log) does not fail runs measured by other metrics.
- The artifact directory always contains the full diff against the pinned simulator revision. `abc-harness export <task_id>` packages the modified source for the researcher.

### Sandbox exec

- Sandbox exec runs the agent's build and test commands in the execution image after approval of a plan with permitted edits. The edited source is read-only there; only the scratch directory is writable. It has no network and no host environment.
- Sandbox exec output never counts as a result. Only simulation runs of the approved plan enter `results.json` and the report.
- The plan's validation check still gates the experiment, whatever the agent's own tests show.
- Every sandbox command and its output go to `trace.jsonl` and `sandbox/`, and the agent's test files stay in the artifact directory.
- Sandbox exec time and the model calls around it count toward the task's limits.

## Execution environment

Simulators run in a prebuilt Docker image with pinned simulator revisions, no network access, and no API key. The harness and model client stay on the host. [architecture.md](architecture.md#execution-environment) describes the mechanism.

## Literature sources

- The first search round covers the venues FC, AFT, and IEEE ICBC. It uses Semantic Scholar when the researcher configures its API key in `.env`, and OpenAlex otherwise. When those venues give nothing relevant, the agent broadens the search to all venues and preprints (OpenAlex, plus Semantic Scholar with a key). More venues are added to the first round over time.
- DBLP is not used: it answers automated requests with a bot check (see [gotchas](context/gotchas.md)). IEEE Xplore may be added when the researcher configures an API key.
- The researcher can keep PDFs in a local library (`papers/`, or `--library`). The harness lists them for the agent and parses one only when the agent opens it; the researcher names a paper in the request to have it read, and the agent checks the list before searching online. An opened library paper can be cited like a found one. Reading a paper keeps nothing; the agent keeps a paper it read with `save_paper`, when the researcher asks or the paper supports an approved plan, optionally in a folder. The harness saves the PDF named by title, records it in the library's `index.json` (keyed by file content, so moved files keep their record), and refuses a duplicate by file, arXiv id, DOI, or title; a later task reads a kept arXiv paper from arXiv's HTML and falls back to the PDF. Above 100 PDFs, the terminal suggests removing some.
- Full text comes from two tracks. For a paper with an arXiv version, the harness reads arXiv's HTML rendering, with tables as text and figures as images; figures in SVG are not viewable. When arXiv has no HTML for the paper, and for every PDF from the local library, the PDF parser (MinerU, in its own container without network) turns the PDF into text, LaTeX formulas, tables, and cropped figure and table images. Papers without an arXiv version that are not in the local library are available by abstract only.
- Text parsed from a PDF is machine-recognized and labelled so in the saved text, the tool result, and the report. In our tests 96 to 98% of sentences matched arXiv's HTML exactly, but table numbers lost decimal points. So the agent cites a value from such a table only as a figure reading, after viewing the table's image; the harness refuses a quote taken from it.
- Parsing a 20-page paper takes 1 to 6 minutes on CPU, mostly for formulas. Each parse is cached by the PDF's content and the parser image, so the same paper is parsed once.
- A plan cites a paper with the parameter, assumption, or metric it supports and either a quote copied from the paper or a figure reading. The harness accepts a citation only if the paper came from a search in the same task or was opened from the local library, and its quote appears verbatim in the abstract or saved full text, or its figure reading names a figure the agent viewed in the task and states an uncertainty. Citations are part of the plan, so the approval covers them, and the review marks figure readings as approximate.
- The artifact directory keeps every search, found paper, figure list, viewed figure, and the source of each full text in `literature.json`, and each full text, PDF, parser output, and viewed figure image in `papers/`. The manifest records each PDF parse with the parser image ID, the MinerU and model revisions, and the time it took. The report lists each citation with the place the harness found its quote, or, for a figure reading, the image it was read from and a note that it is approximate and not checked against text.

## Run and task status

- Each simulation run ends as `completed`, `failed`, `timeout`, or `missing`. A run is `completed` when the simulator exits with status 0 and its expected output parses. A planned run that never started is `missing`.
- Each task ends as `completed`, `partial`, `stopped_by_limit`, `rejected`, `not_executed`, or `failed`. A task is `completed` only when every planned simulation run completed and any validation check passed. A task is `not_executed` when the agent ends without running a plan, for example because no simulator can represent the question.
- The harness writes the report and manifest for every status, including partial and stopped tasks.

## What each task saves

Give each task an ID and an artifact directory. Save the approved plan and all decisions, cited sources, simulator revisions and image digest, configuration, code changes, validation results, random seeds where available, raw output, figures with the scripts that drew them, and a short report.

A chat session (`abc-harness chat`) is a conversation of several tasks: each researcher request runs as its own task with its own approval, report, and limits. The harness gives each new task the earlier tasks' questions, plans, results, figures, and final answers from their records, and lets the agent read their artifact directories; a paper is cited only if found or opened again in the new task.

After a plan runs, the agent may draw static figures of the task's results. It writes a matplotlib script, which the harness runs in the plot image with the results read-only and no network. The script, PNG, and SVG are kept together, and the report shows each figure with its caption and a link to its script, so every plotted value can be traced to the results. Include enough information to rerun the experiment.

Append events to `trace.jsonl` as work happens. Show brief progress, retries, and errors in the terminal. Record model calls with the model's summarized thinking, tool calls, active and waiting time, errors, and the final stop reason. At the end, print the run statistics: time, model calls and tokens, tool calls, and completed simulation runs. Record token usage when the provider supplies it and label cost estimates as estimates.

## Judge

After a task that executed a plan, the researcher may ask a model to judge whether the agent's final answer is supported by the task's results: `abc-harness judge runs/<task_id>`, or `/judge` in chat. The judgment is advice for the researcher, labelled as model-assessed, and never changes the task's status, report, or evidence.

- **When.** Only on request, only for a task that executed a plan, and only when the automatic `trace check` found no `FAIL`: judging reasoning built on contradicted numbers is meaningless. The harness shows the judge model and an estimated cost first and asks before calling it.
- **What the judge sees.** Only saved artifacts: the researcher's question, the executed plan, the harness-computed Results table, the validation verdict, the `trace check` findings (including numbers without a source), and the agent's final answer. Each part has a length cap; nothing is sent to the judge that the task did not already send to a model, and keys are redacted.
- **What it scores.** One dimension in the first version, `conclusion_supported` from 0 to 10: does every claim of the final answer follow from the results, without overstating a difference within the spread or generalising past the tested parameters? The judge must check each number before scoring, and quote the sentences it faults.
- **Which model.** `--model` chooses it; by default the first listed model with a key in `.env` that is not the task's own model, because a model favours its own answers. A judgment by the task's own model is allowed but recorded as such.
- **Limits.** A judgment runs after the task ended, so it does not use the task's limits; it has its own (see [Limits](#limits)).
- **Record.** Each judgment appends one line to `judge.jsonl` in the task directory: the score, the reason and quoted sentences, the judge model and effort, the prompt's hash, token usage, estimated cost, and the time. An unreadable verdict is recorded as `no_verdict`, never guessed. The run statistics show the latest judgment.

## Benchmark

Planned in [M5.3](development-plan.md#m53-model-benchmark-planned); nothing here is built yet. A benchmark compares the listed models on how well they complete research tasks, using only signals the harness already produces.

- **Benchmark tasks.** A fixed set of research requests of two kinds, each ordered by difficulty. A `parameter` task (three of them, from a single SimBlock baseline to a parameter comparison) needs only the simulator's own parameters. A `code` task (two of them, such as a simplified selfish mining strategy) needs a [permitted edit](#permitted-edits) to simulator source and a validation check. Each benchmark task comes with its kind and the checks its result must pass, such as the simulator to use and the metrics the results must contain; a `code` task also fixes the validation check's configuration, expected value, and tolerance.
- **Matrix.** Every chosen model runs every benchmark task a fixed number of times (two or three), because one run of a model is not a reliable measurement. Tasks run one after another, since Docker's memory fits one simulation at a time. Each task keeps its own limits ([Limits](#limits)) and its full artifact directory.
- **Approval.** The benchmark command approves every plan, and the record says so ([Approval lifecycle](#approval-lifecycle)). No plan is checked or refused before it runs; the task limits ([Limits](#limits)) and the [permitted edits](#permitted-edits) still apply in code, so an unreviewed plan can cost money but cannot escape the task workspace.
- **Plan deviations.** After each task, the benchmark command compares the executed plan with its benchmark task and records each deviation as a fact, without judging it: a `parameter` task whose plan permitted edits, a `code` task whose validation check differs from the fixed one (configuration, expected value, or tolerance), and a simulator or metric other than the benchmark task names. A deviation does not change the task's status; the researcher decides how to count it when reading the results.
- **No researcher.** A clarification question gets a fixed reply that no researcher is available and the agent should decide from the request and state its assumption. The number of such questions is recorded.
- **Cost.** A pilot of two models on one `parameter` task and one `code` task measures the cost of one task of each kind; a `code` task is expected to cost several times more. Before a benchmark starts, the harness shows the matrix and an estimated cost from the pilot and asks before running it.
- **What each task records.** One line per task in `runs/bench/<bench_id>/results.jsonl`: model, effort, benchmark task and its kind, repetition, task ID and directory, task status, validation verdict (and for a `code` task whether the edited source built and how many sandbox exec calls it took), the `trace check` counts of `FAIL` findings and numbers without a source, the [judgment](#judge) score, estimated cost, model calls, tokens, active runtime, clarification questions, and the plan deviations. A missing value is recorded as missing, never filled in. An interrupted benchmark resumes by running only the matrix cells not yet in `results.jsonl`.
- **Judgment.** One judge model is fixed for the whole benchmark and recorded. Tasks by the judge model itself are judged by a second model, and the record says so. A task with a `trace check` `FAIL`, or one that executed no plan, gets no judgment, as [Judge](#judge) requires.
- **Benchmark charts.** A separate command reads only `results.jsonl` and draws PNG charts with matplotlib, without calling a model, so a chart can be redrawn after its code changes: completion rate as line charts, one panel per kind on a shared vertical axis (benchmark tasks in difficulty order on the horizontal axis, one line per model); a line chart comparing the kinds, with each model's completion rate on `parameter` tasks joined to its rate on `code` tasks; judgment scores as a box plot per model, split by kind; estimated cost against mean judgment score as a scatter plot, one marker shape per kind; and `trace check` findings as a stacked bar chart per model. A `code` task's chart also shows how many tasks failed at the validation check, apart from other failures. Every chart marks tasks with a plan deviation, so a completion that loosened its validation check is never shown as an ordinary one. Each chart names the benchmark ID and the date, and labels judgment scores as model-assessed.


| Capability | How to verify it |
|---|---|
| Simulator integration | Run one real example with each supported simulator. Record its revision, command, configuration, and output. |
| Literature retrieval | Give the agent a question that needs a reference without supplying a paper. Verify that it finds a relevant source and uses it to justify a specific choice in the plan. |
| Library paper | Put a paper's PDF in the local library and name it in the request. Verify that the report cites it, that the citation is labelled as machine-recognized, and that a value from one of its tables is cited as a figure reading. |
| Simulator selection | Verify that the agent explains its choice using the capabilities required by the experiment. If neither simulator fits, it identifies the missing capability. |
| Plan approval | Approving a plan allows the corresponding run to start. Rejecting it starts no simulator container. Revising it requires approval of the new version. |
| Permitted edits | A change to a simulator source file the approved plan does not permit, and any write outside the task workspace, is refused; builds and tests in `scratch/` are allowed. Agent-written code that fails its validation check stops the task, and the report explains why. |
| Result verification | Match planned configurations and repetitions against completed runs. Recalculate a reported metric from raw output. A deliberately omitted run must appear as missing in the report. |
| Controlled stopping | Exercise the time and call limits using smaller test budgets. Verify that the harness stops, removes active containers, and retains the trace and available results. |

## Delivery order

The [development plan](development-plan.md) lists the milestones, their demonstrations, and their acceptance checks. In short: first run an ordinary SimBlock example from plan approval to a checkable result, then add the agent loop, BlockSim and simulator selection, literature retrieval, and agent-written code. The MVP demonstration compares honest mining and selfish mining across mining-power shares, measuring reward share. Before treating the results as validated, document the strategy reference, reward definition, baseline, and simulator assumptions. An unexpected result is a valid outcome to report.
