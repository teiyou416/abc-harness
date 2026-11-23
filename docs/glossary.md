# Glossary

The words ABC Harness uses for research tasks, experiments, and evidence. Use
these terms in code, docs, prompts, and reports, and avoid the alternatives
listed under each.

## Tasks and experiments

**Task**:
One research request, with one task ID, one artifact directory `runs/<task_id>/`, one trace, and one set of limits. A chat reply's artifact directory moves into its chat session's directory when it ends.
_Avoid_: job, session, run (a run is a simulation run)

**Plan version**:
One immutable revision of a plan, identified by its content hash. An approval applies to exactly one plan version.
_Avoid_: plan draft, plan revision number

**Simulation run**:
One simulator invocation for one configuration and one seed. A task usually contains many simulation runs.
_Avoid_: experiment, trial, job

**Chat session**:
A conversation started with `abc-harness chat`. Each request in it runs as its own task; the next task learns about the earlier ones from a block the harness writes from their records.
_Avoid_: thread, conversation task

**Chat reply**:
A task in a chat session that ended without proposing a plan. When it ends, the harness moves its artifact directory to `runs/sessions/<session_id>/replies/<task_id>/`, so `runs/` itself holds only tasks with a plan.
_Avoid_: chat task, small talk

**Task workspace**:
`runs/<task_id>/workspace/`, the task's copy of the simulator source, where every file change for the task happens.
_Avoid_: sandbox, scratch directory

**Execution image**:
A prebuilt Docker image, one per simulator, holding that simulator at a pinned commit with its dependencies.
_Avoid_: container, environment

**Runner**:
The harness component that starts every container: the simulation runs of an approved plan, sandbox exec commands, PDF parses, and figure scripts.
_Avoid_: executor, launcher

**Sandbox exec**:
The tool that runs the agent's own build and test commands inside the execution image after approval.
_Avoid_: shell, terminal

**Test double**:
A fake model, runner, simulator, or HTTP response used in tests. Results from a test double are labelled as such.
_Avoid_: mock (for these project-level fakes)

**Permitted edit**:
A source file an approved plan lets the agent create or change, with its purpose. Approval covers the scope of the change, not a specific diff.
_Avoid_: allowed file, patch, change request

**Custom metric**:
A metric a plan with permitted edits defines by name and definition, because no built-in metric measures it. The edited source prints it as an `ABC_METRIC <name>=<value>` line; the harness reads it from the run's raw output.
_Avoid_: redefined metric, agent metric

**Validation check**:
The plan's test of agent-written code: a configuration whose metric must match an expected value within a tolerance. The harness runs it once before any configuration; if it fails, the task stops.
_Avoid_: unit test, sanity check, acceptance test

**Edited source**:
The agent's copy of the simulator source in the task workspace, holding its permitted edits. A configuration runs either the edited source or the original source.
_Avoid_: modified simulator, fork, patched source

**Result figure**:
A figure the agent draws from the task's own results with `make_figure`, kept with the script that drew it. Not to be confused with a figure in a paper, which the agent views.
_Avoid_: plot, chart, graph

**Plot image**:
The container image that runs the agent's figure scripts, with the task's results read-only and no network.
_Avoid_: plotting container, matplotlib sandbox

**Benchmark** (planned):
A fixed set of benchmark tasks that several models each run a fixed number of times, so their task completion, judgment scores, and cost can be compared. Its data lives in `runs/bench/<bench_id>/`.
_Avoid_: evaluation (a judgment is not an evaluation suite), eval, leaderboard

**Benchmark task** (planned):
One research request in a benchmark, with the checks its result must pass. Each run of it by a model is an ordinary task.
_Avoid_: test case, scenario

**Benchmark envelope** (planned):
The limits the researcher approves once before a benchmark: simulators, parameter ranges, metrics, and permitted edits. The harness approves a plan version inside it in code and refuses any other.
_Avoid_: auto-approval, policy

**Benchmark chart** (planned):
A PNG the chart command draws with matplotlib from a benchmark's `results.jsonl` alone. Not a result figure, which the agent draws from one task's results.
_Avoid_: figure, report

## Evidence

**Judgment**:
A model's score of whether a finished task's final answer is supported by its results, made only when the researcher asks (`abc-harness judge`, `/judge`) and recorded in `judge.jsonl`. It is advice labelled as model-assessed, never evidence, and never changes the task.
_Avoid_: evaluation, grade, review (a review is the researcher's decision on a plan)

**Grounded number**:
A number in the agent's final answer that some number the task saw or produced rounds to: a tool result, the researcher's message, the plan, `results.json`, or a report table, never the agent's own words. `trace check` warns about each number that is not grounded; such a number is not a failure, since the agent may have derived it.
_Avoid_: verified number, cited number

**Found paper**:
A paper that a literature search returned during the task. Found papers and library papers the agent opened are the only ones that can be cited.
_Avoid_: source, reference

**Local library**:
The researcher's folder of PDFs (`papers/` unless `--library` names another). The agent sees every PDF in it listed by file name, and the harness parses one only when the agent opens it; the researcher points the agent at a paper by naming it in the request. A library paper the agent opened can be cited like a found paper. When the researcher asks, or a paper supports an approved plan, the agent can keep a paper it read in the library with `save_paper`, named by its title; the library's `index.json` records its arXiv id and DOI and prevents keeping it twice.
_Avoid_: paper folder, thesis folder, supplied paper

**PDF parser image**:
The container image that turns one PDF into text, formulas, tables, and cropped figure images, without network. Its parse time does not count toward the task's time limit.
_Avoid_: MinerU container, OCR service

**Machine-recognized text**:
A full text the PDF parser produced. It may differ from the paper in places, notably table numbers, so values from its tables are cited as figure readings.
_Avoid_: OCR text, extracted text

**First-round venues**:
The venues every literature search starts from: FC, AFT, and ICBC. A broadened search drops this restriction.
_Avoid_: configured sources, default venues

**Citation**:
An entry in a plan that ties one found or library paper to the parameter, assumption, or metric it supports. Every citation rests on either a quote or a figure reading.
_Avoid_: reference, source

**Quote**:
A passage copied verbatim from a found or library paper's abstract or saved full text. The harness confirms it appears there, and refuses one taken from a table of machine-recognized text.
_Avoid_: excerpt, snippet, evidence text

**Figure reading**:
A value the model reads off a figure it viewed during the task (or a table image, for machine-recognized text), stated with its uncertainty. It is approximate and cannot be checked against text.
_Avoid_: figure value, extracted data, digitized value
