# Glossary

The words ABC Harness uses for research tasks, experiments, and evidence. Use
these terms in code, docs, prompts, and reports, and avoid the alternatives
listed under each.

## Tasks and experiments

**Task**:
One research request, with one task ID, one artifact directory `runs/<task_id>/`, one trace, and one set of limits.
_Avoid_: job, session, run (a run is a simulation run)

**Plan version**:
One immutable revision of a plan, identified by its content hash. An approval applies to exactly one plan version.
_Avoid_: plan draft, plan revision number

**Simulation run**:
One simulator invocation for one configuration and one seed. A task usually contains many simulation runs.
_Avoid_: experiment, trial, job

**Task workspace**:
`runs/<task_id>/workspace/`, the task's copy of the simulator source, where every file change for the task happens.
_Avoid_: sandbox, scratch directory

**Execution image**:
A prebuilt Docker image, one per simulator, holding that simulator at a pinned commit with its dependencies.
_Avoid_: container, environment

**Runner**:
The tool that executes the simulation runs of an approved plan.
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

## Evidence

**Found paper**:
A paper that a literature search returned during the task. Found papers and supplied papers are the only ones that can be cited.
_Avoid_: source, reference

**Supplied paper**:
A paper the researcher hands to a task as a PDF file. It is parsed before the agent starts and can be cited like a found paper.
_Avoid_: local paper, uploaded paper, attachment

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
An entry in a plan that ties one found paper to the parameter, assumption, or metric it supports. Every citation rests on either a quote or a figure reading.
_Avoid_: reference, source

**Quote**:
A passage copied verbatim from a found or supplied paper's abstract or saved full text. The harness confirms it appears there, and refuses one taken from a table of machine-recognized text.
_Avoid_: excerpt, snippet, evidence text

**Figure reading**:
A value the model reads off a figure it viewed during the task (or a table image, for machine-recognized text), stated with its uncertainty. It is approximate and cannot be checked against text.
_Avoid_: figure value, extracted data, digitized value
