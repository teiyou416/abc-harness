# Architecture

This page describes the system as it is built today and which module holds
each part. The diagram below is the current architecture; keep it true in the
same commit as any change that makes it false. The values of all limits are in
[the project specification](project-spec.md#limits).

```mermaid
flowchart TB
    R(["Researcher"])

    subgraph CLI["interfaces/"]
        ASK["ask: question"]
        CHAT["chat: conversation,<br/>one task per request"]
        RUN["run: plan file"]
    end

    subgraph LOOP["Agent: agent/"]
        CTX["Context window: agent/context.py<br/>system = SOUL.md + rules.md<br/>soft and hard context limits"]
        LLM["Model client: agent/model.py<br/>only holder of the API keys<br/>Claude or DeepSeek"]
        TOOLS["Tools: tools/<br/>describe_simulator, read_file, search_files, search_papers, read_paper,<br/>save_paper, view_figure, ask_researcher, propose_plan,<br/>write_file, edit_file, run_command, run_plan,<br/>make_figure"]
        CTX --> LLM -->|tool request| TOOLS -->|tool result| CTX
    end

    subgraph TASK["Task: execution/task.py"]
        PLAN["planning/plan.py<br/>validate, version = SHA-256"]
        APPROVAL["planning/approval.py<br/>decisions recorded by the harness"]
        LIMITS["execution/limits.py<br/>active time and model-call limits"]
        EXEC["execute approved plan"]
    end

    subgraph SIM["simulators/"]
        ADAPTER["simblock.py, blocksim.py + capability cards<br/>parameter patch, seed, metrics"]
    end

    subgraph DOCKER["Execution images, no network, no host env"]
        RUNNER["execution/runner.py: one container per simulation run"]
        SIMBLOCK["SimBlock image: JDK 21 + pinned commit"]
        BLOCKSIM["BlockSim image: Python 3.11 + pinned commit"]
        PDFIMG["PDF parser image: MinerU, models built in"]
        PLOTIMG["Plot image: matplotlib + abcplot"]
        RUNNER --> SIMBLOCK
        RUNNER --> BLOCKSIM
        RUNNER --> PDFIMG
        RUNNER --> PLOTIMG
    end

    subgraph ART["runs/task_id/"]
        FILES["approvals.jsonl, plans/, plan.json<br/>raw/, changes/, results.json<br/>report.md, manifest.json<br/>trace.jsonl, history.md"]
    end

    subgraph LIT["Literature: literature/"]
        LIB["Library: literature.json, papers/<br/>citations checked against it"]
        PDF["pdf.py: MinerU output to text, figures, tables"]
        LIB --> PDF
    end

    ENV[(".env")] -->|keys| LLM
    ENV -->|optional S2 key| LIB
    TOOLS -->|search_papers, read_paper, save_paper, view_figure| LIB
    LIB <-->|HTTPS from the host| ACADEMIC(["OpenAlex, Semantic Scholar, arXiv"])
    R -->|--paper or /paper PDF| LIB
    LIB -->|parse a PDF, via the task| RUNNER
    LIB --> FILES
    LLM <-->|Messages API| CLAUDE(["Claude API"])
    LLM <-->|Anthropic-compatible API| DEEPSEEK(["DeepSeek API"])
    R --> ASK --> LOOP
    R --> RUN --> PLAN
    TOOLS --> PLAN
    TOOLS -->|show plan, ask| R
    R -->|approve / revise / reject| APPROVAL
    TOOLS -->|run_plan| EXEC
    APPROVAL -->|required| EXEC
    LIMITS -.->|checked before every call and run| LOOP
    EXEC --> ADAPTER --> RUNNER
    EXEC --> FILES
    LOOP -->|trace, history| FILES
```

The [module map](#module-map) says what every file does. Each simulator adapter ships a capability card next to it,
for example `simulators/simblock_card.md` and `simulators/blocksim_card.md`.
The agent reads every card before choosing a simulator and cites entries of
both in the plan's rationale.

## Module map

The package `src/abc_harness/` has one folder per layer; `planning/` and `literature/` share the lowest layer above the simulators. A module imports only
from its own layer or a lower one; `tests/test_rulebook.py` checks this, and it
checks that every module appears in this table.

| Layer (high to low) | File | What it does |
|---|---|---|
| Entry | `interfaces/__init__.py` | Names the entry points of the package. |
| Entry | `interfaces/cli.py` | Commands `image build`, `run`, `ask` (with `--paper`), `chat`, `trace summary`, `trace check`, `export`; shows plans and questions in the terminal. Holds no task logic. |
| Entry | `interfaces/chat.py` | The `chat` loop: reads a line (prompt_toolkit, with history), runs slash commands, sends anything else to the chat session, and turns Ctrl-C during a task into stopping that task. |
| Entry | `interfaces/console.py` | Shows a status line redrawn in place for the current action, with each tool call, milestones, errors, and the final answer above it (`Console`) and the run statistics at the end of a task (`task_summary`). |
| Entry | `__init__.py` | Version number and the `abc-harness` entry point. |
| Agent | `agent/loop.py` | The agent loop: call the model, run the requested tools, compress the context at the soft limit. |
| Agent | `agent/session.py` | A chat session: runs each request as a new task, writes the earlier tasks into the next task's first message from their records, and logs the session in `runs/sessions/<id>/session.jsonl`. |
| Agent | `agent/model.py` | The model client for Anthropic's Messages API and DeepSeek's Anthropic-compatible one; the list of supported models with their provider, list price, and whether they see images; the only code that receives a model API key. Caps connection attempts at 5 seconds and retries transient failures up to three times within the remaining task time. The terminal shows each retry and its delay. |
| Agent | `agent/context.py` | Token estimates, `history.md`, and the message that starts a new window. |
| Agent | `agent/secrets.py` | Reads API keys from `.env` and redacts them from traces. |
| Agent | `agent/prompts/` | `SOUL.md` (identity), `rules.md` (workflow), `compact.md` (summary instructions). |
| Tools | `tools/__init__.py` | The explicit list of tools the agent can call. |
| Tools | `tools/base.py` | `ToolContext` (shared task state), `ToolOutput` (a result with images), `ToolError` (refusal), `EndTask` (ends the task). |
| Tools | `tools/describe_simulator.py` | Returns a simulator's capability card. |
| Tools | `tools/search_papers.py` | Searches the first-round venues, or everything when broadened. |
| Tools | `tools/save_paper.py` | Keeps a paper the agent read in the local library, optionally in a folder, after checking the library index for the same file, arXiv id, DOI, or title. |
| Tools | `tools/read_paper.py` | Opens a paper's full text (arXiv HTML, or a PDF parsed by MinerU) in `papers/` and returns its source, outline, and figure and table list. |
| Tools | `tools/view_figure.py` | Shows the model one figure (or, for a PDF, a table) as an image and records that it was viewed. |
| Tools | `tools/read_file.py` | Reads lines of a file, or lists a folder, under the roots in `tools/paths.py`, nothing else. |
| Tools | `tools/search_files.py` | Searches the same paths: matching lines as `path:line: text` for a regular expression, or file names for a glob. |
| Tools | `tools/paths.py` | The readable roots (`examples/`, `source/<simulator>/`, `task/`, and in a chat session `previous/<task_id>/`) and the path check shared by `read_file` and `search_files`. |
| Tools | `tools/ask_researcher.py` | Asks the researcher a question; the wait is not active time. |
| Tools | `tools/propose_plan.py` | Validates a plan and its citations, pins the image, and gets the researcher's decision. |
| Tools | `tools/run_plan.py` | Runs an approved plan and summarises the results, including the validation check, for the model. |
| Tools | `tools/make_figure.py` | After `run_plan`, runs the agent's matplotlib script in the plot image and shows it the PNG. |
| Tools | `tools/write_file.py` | Writes a whole permitted source file, or a file under `scratch/`, after approval. |
| Tools | `tools/edit_file.py` | Replaces one exact passage in such a file. |
| Tools | `tools/run_command.py` | Sandbox exec: runs a build or test command in the execution image. |
| Tools | `tools/edits.py` | The rule the three code tools share: only for an approved plan with permitted edits, and only until it runs. |
| Execution | `execution/task.py` | One task end to end: artifact directory, plan versions, image pinning, PDF parsing with its cache, sandbox exec, the validation check, simulation runs, final artifacts. |
| Execution | `execution/runner.py` | Docker: one container per simulation run, sandbox command, or PDF parse, no network, label-based cleanup. |
| Execution | `execution/workspace.py` | The original, edited, and scratch trees; which paths a write may touch; the diff of the edits. |
| Execution | `execution/figures.py` | Runs one figure script in the plot image with the results read-only, checks its PNG, and keeps script, PNG, SVG, and log in `figures/` with `figures/index.json`. |
| Execution | `execution/export.py` | `abc-harness export`: packages the edited source with the plan, diff, and validation result. |
| Execution | `execution/limits.py` | The active-time and model-call limits; waiting for the researcher and PDF parsing do not count. |
| Execution | `execution/trace.py` | Writes `trace.jsonl`, passes each redacted event to an optional listener (the live terminal output), and summarises it. |
| Execution | `execution/trace_check.py` | Audits approval and validation order and checks saved result tables offline. |
| Execution | `execution/recompute.py` | Independent standard-library metric calculations, also available as the standalone recomputation script. |
| Execution | `execution/report.py` | Writes `report.md`, `results.json`, and `manifest.json`. |
| Planning | `planning/plan.py` | Plan format, validation, version hash, and the text the researcher reviews. |
| Planning | `planning/approval.py` | Records decisions in `approvals.jsonl` and refuses unapproved versions. |
| Literature | `literature/__init__.py` | The public names of the literature layer. |
| Literature | `literature/library.py` | `Literature` (the services and the Semantic Scholar key) and `Library` (one task's papers, figures, and views in `literature.json`; the quote check). |
| Literature | `literature/openalex.py` | OpenAlex search: request URL and response parsing. |
| Literature | `literature/semantic_scholar.py` | Semantic Scholar search: request URL and response parsing. |
| Literature | `literature/pdf.py` | Turns MinerU's output for a PDF into the same text lines and figure list, with tables as viewable figures; the parser image name and timeout. |
| Literature | `literature/fulltext.py` | Turns arXiv's HTML rendering of a paper into text lines, Markdown tables, an outline, and a figure list. |
| Literature | `literature/figures.py` | The `Figure` record, and an image's format, size, and token cost read from its header. |
| Literature | `literature/papers.py` | The `Paper` record, paper IDs, and the text normalisation used to match quotes. |
| Literature | `literature/http.py` | HTTP requests with per-host pauses and retries that fit the task's remaining time. |
| Simulators | `simulators/__init__.py` | The registry of supported simulators. |
| Simulators | `simulators/base.py` | The interface every simulator adapter implements. |
| Simulators | `simulators/simblock.py` | SimBlock adapter and `simblock_card.md`. |
| Simulators | `simulators/blocksim.py` | BlockSim adapter (Bitcoin model) and `blocksim_card.md`. |

One `ask` passes through the layers in this order:

```
interfaces/cli.py -> agent/loop.py <-> agent/model.py
            -> tools/propose_plan.py -> planning/plan.py -> execution/task.py (pin image)
               -> interfaces/cli.py (researcher decides) -> planning/approval.py
            -> tools/run_plan.py -> execution/task.py -> simulators/<name>.py -> execution/runner.py
          -> execution/task.py (close) -> execution/report.py, execution/trace.py
```

## Agent tools

The agent has thirteen tools, one module each in `tools/`: `describe_simulator`,
`read_file`, `search_files`, `search_papers`, `read_paper`, `save_paper`, `view_figure`, `ask_researcher`,
`propose_plan`, `write_file`, `edit_file`, `run_command` (sandbox exec),
`run_plan`, and `make_figure`. The three code tools work only after the researcher approved a plan
with permitted edits; `make_figure` works only after a plan ran, needs no
approval of its own because it changes no experiment, and counts toward the
task's time limit. Each module
holds the definition sent to the model and the harness code that runs it;
`agent/loop.py` keeps only the loop, context compression, and the dispatch by tool
name. The harness validates every
proposed plan in code before the researcher sees it, records each decision
itself, and refuses `run_plan` for any plan version without a recorded
approval. A rejection ends the task without another model call. A plan's
citations pass only if each paper came from `search_papers` in the same task
or was supplied by the researcher,
and its quote appears verbatim in the paper's abstract or saved full text or
its figure reading names a figure the agent viewed, with an uncertainty.

## Chat sessions

`abc-harness chat` keeps a conversation going, but each researcher request
still runs as its own task, with its own artifact directory, approval,
report, and limits. A task executes at most one plan, as before. What the
agent remembers of the conversation is a block the harness writes from the
earlier tasks' records (question, plan, results table, figures, the agent's
final answer; the latest five in full), added to the new task's first
message; the earlier artifact directories are readable at
`previous/<task_id>/`. Papers must be found again in each task before they
are cited; papers added with `/paper` or `--paper` are parsed into every task
of the session (the parse cache makes this instant).

## Data flow

1. The CLI creates a task, its artifact directory, and its trace.
2. The agent loop sends the system prompt, the researcher's request, and the
   conversation to the model.
3. The model requests a tool. The harness checks the request against the
   limits and the approval state, executes it, writes a trace event, and
   returns the result to the model.
4. When a choice needs evidence, the model searches the literature and reads
   full texts. The harness performs every request from the host, so the
   execution images stay offline, and records each paper in `literature.json`.
   A full text comes from arXiv's HTML or, when there is none, from the arXiv
   PDF parsed in the PDF parser image. PDFs the researcher supplies with
   `ask --paper` are parsed before step 2 and listed in the first message.
   PDFs in the local library (`--library`, default `papers/`) are listed
   there unparsed, with the title from an earlier parse if the parse cache
   has one; `read_paper` parses one when the agent opens it. Reading keeps
   nothing; `save_paper` copies a read paper's PDF into the library (or a
   folder of it), named by its title. The library's `index.json` maps each
   file's SHA-256 to its path, title, arXiv id, and DOI, follows files the
   researcher moves, and is checked before saving so no paper is kept twice.
   Later tasks read a kept arXiv paper from arXiv's HTML.
5. The model drafts a plan. The harness checks its citations, pins the execution image's ID into
   it, the Human Interaction tool shows it to the researcher, and the harness
   records the decision for that plan version.
6. If the plan permits edits, the agent changes those files with `write_file`
   and `edit_file`, and builds and tests them with `run_command`: the edited
   source is mounted read-only and `scratch/` is the only writable directory.
7. At `run_plan`, the harness freezes the edits, refuses any change to a file
   the plan does not permit, saves the full diff, and runs the validation check
   on the edited source. A failed check stops the task.
8. The runner executes simulation runs in exactly the pinned image ID, even if
   the image tag was rebuilt in the meantime, on the edited or the original
   source as each configuration says.
   The report step matches planned runs against completed runs and computes
   metrics from raw output.
9. The loop ends when the model finishes, the researcher rejects the plan, or a
   limit stops the task. The harness writes the report and manifest in every
   case.

## Context management

The agent's input is the system prompt (`agent/prompts/SOUL.md`, then
`agent/prompts/rules.md`), the tool definitions, and the messages of the current
window. `agent/context.py` holds the limits and the pieces below, and `Agent.run`
applies them.

- Before every model call the agent estimates the next input from the last
  reported input tokens, the reply, and the new tool results. Past the soft
  limit it compresses first. An input that would leave less than one full
  reply (thinking included) inside the hard limit stops the task with reason
  `context`.
- Compression asks the model, with `agent/prompts/compact.md` and no tools, for a
  summary of bounded length; the call has its own reply cap because its
  thinking counts too. The summary call counts toward the call limit.
- The new window is one user message: the original question, a task-state
  block written from the harness's records (plan versions, decisions,
  clarification answers, run results), the summary, the latest tool results,
  and a pointer to `task/history.md`. Plan versions, decisions, and numbers
  never pass through the summary.
- `history.md` receives every message of every window as it happens, with
  full tool results. A tool result longer than its cap is cut in the
  window, and the cut notice points to its full text in `history.md`. The
  agent pages through files with `read_file` `offset` and `limit`.
- Requests mark the system prompt as a cache breakpoint and enable automatic
  caching of the conversation tail.
- The manifest records the SHA-256 of each prompt file and the number of
  context windows.

## Execution environment

- Each simulator has its own image, built from `docker/<simulator>/Dockerfile`
  with `abc-harness image build`. The SimBlock image is a digest-pinned
  `eclipse-temurin:21-jdk` plus the SimBlock source at a pinned commit, checked
  by SHA-256. Each plan pins the image ID it runs in, and each task manifest
  records that ID and the simulator commit. Rebuilding an image therefore
  changes the version of every new plan.
- SimBlock reads its parameters from Java constants and hard-codes its random
  seed, so every simulation run gets its own source copy with the planned
  constants and seed written in, and compiles it with `javac` in its container.
  The upstream Gradle wrapper is not used.
- The BlockSim image is a digest-pinned `python:3.11-slim` with pandas 1.5.3
  (BlockSim calls `ExcelWriter.save()`, which pandas 2 removed) and the
  BlockSim source at a pinned commit. The adapter selects the Bitcoin model,
  writes planned values into its block of `InputsConfig.py`, forces one
  upstream run per simulation run, and seeds `random` and `numpy.random` in
  `Main.py`. `docker/blocksim/xlsx_to_csv.py` turns BlockSim's Excel result
  into one CSV per sheet so metrics can be recalculated with the standard
  library.
- The harness and the model client run on the host. The API key never enters a
  container: the docker CLI receives only an allowlist of Docker variables, and
  containers receive no host variables at all.
- The harness copies the simulator source from the image into the task
  workspace the first time the agent reads it or a plan runs:
  `workspace/original/<simulator>/` stays unchanged, `workspace/edited/` is the
  agent's copy, and `workspace/scratch/` holds its builds and tests. Each
  simulation run gets its own copy of the original or the edited source, and
  its container mounts only that run's directory.
- Sandbox exec runs the agent's commands in the same image with the edited
  source mounted read-only at `/work/src` and `scratch/` writable at
  `/work/scratch`, with the same network, environment, resource, and label
  rules as simulation runs. Each command and its full output go to
  `sandbox/<n>.log` and the trace; its time counts toward the task's limit.
- Containers run with `--network none`, CPU and memory limits, and a task label.
  On a timeout or limit, the harness stops and removes every container with that
  label. If removal fails (for example, the Docker daemon is unreachable), the
  harness records the error in the trace, the manifest, and the report, and
  still writes the results and the final status.
- The PDF parser image (`docker/mineru/Dockerfile`) is a digest-pinned
  `python:3.12-slim` with a pinned MinerU release and its CPU models (about
  0.8 GB) downloaded at build time; the whole image is about 3.2 GB. One
  container parses one PDF, with the PDF mounted read-only, an output
  directory writable, no network, its own CPU and memory limits, and the
  task label. It has its own timeout, and its time is recorded as
  `pdf_parse_seconds` instead of counting toward the task's limit. Its output
  is cached under `runs/.cache/pdf/<image id>/<PDF sha256>/` and copied into
  each task that needs it.
- The plot image (`docker/plot/Dockerfile`) is the same digest-pinned
  `python:3.12-slim` with pinned matplotlib and numpy and the `abcplot`
  helper (`docker/plot/abcplot.py`: loads the results, applies the house
  style, saves SVG and PNG). One container runs one figure script, with
  `results.json`, `plan.json`, `validation.json`, and `raw/` read-only under
  `/data`, only `/out` writable, no network, the simulation container's CPU and memory
  limits, the task label, and its own timeout.
- Nothing is installed at runtime. A new dependency means a new image, which
  requires a new plan version and fresh approval.
