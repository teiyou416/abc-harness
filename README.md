# ABC Harness

ABC Harness is a local CLI that turns a researcher's question into a
reproducible blockchain simulation. The researcher reviews an experiment plan
and approves it. The harness then runs the simulator in a Docker container and
writes a report linked to the raw output.

An agent drafts the plan from a research question, reads papers to justify
it, and can change the simulator source within the files the plan permits; a
hand-written plan runs too.
[docs/status.md](docs/status.md) says what works today.

## Requirements

- macOS on Apple silicon (other platforms are untested)
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop or another Docker-compatible runtime, running, with enough
  memory to parse a PDF beside a simulation run (see [Limits](docs/project-spec.md#limits))
- Network access for the first `uv sync` and the image build

## Run the SimBlock example

These are the commands used to produce the M1 example run.

```bash
uv sync
uv run abc-harness image build
uv run abc-harness run examples/simblock-baseline.toml
```

`image build` creates four images (about 4.5 GB in all; build one with `--only`):

- `abc-harness-sim:simblock-8a1285a`: SimBlock at commit
  `8a1285aa37b832385b0be2ae6f804885a4a7031f` with JDK 21.
- `abc-harness-sim:blocksim-603361d`: BlockSim at commit
  `603361dab49101cdd820dbfd86e19536d841cbae` with Python 3.11 and pandas 1.5.3.
- `abc-harness-pdf:mineru-4.2.3`: the PDF parser, MinerU 4.2.3 with its CPU
  models, used to read papers given as PDF. Parsing needs more memory than a
  simulation run; see the requirements above.
- `abc-harness-plot:mpl-3.11.2`: matplotlib 3.11.2 and numpy 2.5.4, used to
  run the figure scripts the agent writes after an experiment.

`uv run abc-harness run examples/blocksim-baseline.toml` runs the BlockSim
example the same way.

`run` prints the plan and asks `Approve this plan? [approve/reject]:`.

- Answer `approve` to run the 10 simulation runs (about 30 seconds). The
  command prints `Artifacts: runs/<task_id>`.
- Answer `reject` to stop. The command prints `No simulator was started.` and
  still writes the decision, the trace and a report.

## Ask the agent

Copy `.env.example` to `.env` and set `DEEPSEEK_API_KEY` for the default
model, or `ANTHROPIC_API_KEY` for a Claude model (see [Models](#models)). The
harness reads each key from this file and passes it only to that provider's
client; it never enters a container, a trace, or git.

```bash
cp .env.example .env   # then edit .env
uv run abc-harness ask "With 300 nodes, does a 30 s block interval produce more orphans than 600 s?"
```

The agent may ask clarification questions, then shows a plan and asks
`Approve this plan? [approve/revise/reject]:`. Choose `revise` to send it
back with a comment; every new version needs a fresh approval.

Each task stops at its limits on active runtime and model calls; change them
with `--time-limit-seconds` and `--llm-call-limit` (defaults in
[Limits](docs/project-spec.md#limits)).

During a task, one status line at the bottom of the terminal says what the
task is doing now, such as `Thinking`, `Using read_file task/plan.json`, or
`Running simulation 132/216`, with the task's elapsed time; it is redrawn in
place, not scrolled. Milestones (plan decisions, the validation result, saved
figures), retries, errors, and the final answer stay on screen above it. Use
`--quiet` to hide live progress. See `trace.jsonl` and `history.md` for details. At the
end, `ask` and `run` print the agent's summary and the run statistics: active
and waiting time, model calls and tokens, an estimated cost at list prices
(`MODELS` in `src/abc_harness/agent/model.py`, from the official pricing page; not a bill), tool
calls, and completed simulation runs. The experiment's results are in `report.md`.

To have the agent read a paper you choose, pass the PDF; repeat `--paper` for
several. The harness parses each one before the agent starts (1 to 6 minutes
for a 20-page paper, not counted toward the task's time limit, and cached for
the next task), and the agent can cite them:

```bash
uv run abc-harness ask "Reproduce Figure 2 of this paper." --paper ~/papers/selfish-mining.pdf
```

Papers you keep for reference go in `papers/` (another folder with
`--library DIR`), named by their titles. The agent sees the list, checks it
before searching online, and parses only the papers it opens; a parsed paper's
own title appears in the list from then on.

### Models

`--model` (and `/model` in chat) takes one of: `deepseek-flash` (default),
`deepseek-v4-pro`, `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`,
and `claude-fable-5-2`. The DeepSeek models need `DEEPSEEK_API_KEY` in `.env`
and send your question, papers, and results to DeepSeek's servers.
`deepseek-v4-pro` cannot see images, so it cannot read figures in papers or
check the figures it draws.

### Chat

Ready-made prompts, in Chinese, Japanese, and English, are in `examples/prompts/`;
`examples/prompts/common-ancestor-reproduction.md` reproduces a stubborn-mining
experiment from a paper and draws a comparison figure.

For follow-up questions, start a conversation instead:

```bash
uv run abc-harness chat [--paper paper.pdf]
```

Type a request and press Enter (Alt+Enter, or Esc then Enter, for a new
line; the arrow keys recall earlier input). Each request runs as its own
task, with its own directory, approval, report, and limits, so a
follow-up such as "now with 1000 nodes" gets a new plan to approve. The agent
remembers the earlier tasks of the conversation: the harness gives it each
one's question, plan, results, figures, and final answer, and it can read
their files. Ctrl-C during a task stops that task and returns to the prompt;
Ctrl-C or Ctrl-D at an empty prompt leaves. Commands: `/tasks` lists the
conversation's tasks, `/paper <pdf>` adds a paper for every following task,
`/model` shows the model and the available ones and `/model <name>` switches
the following tasks to another listed model,
`/new` starts over, `/help`, and `/quit`. The conversation's log is
`runs/sessions/<session_id>/session.jsonl`.

`uv run abc-harness trace summary runs/<task_id>` counts the task's model
calls, tokens, tool calls, and errors.

Run `uv run abc-harness trace check runs/<task_id>` to audit saved evidence offline.
It compares run starts with the plan version and approval records, checks that edited plans passed
validation before formal runs, and checks completed runs against raw output, results.json, and the two
metric tables in report.md. Custom metrics are checked against printed values only.
Exit codes: 0 for consistent evidence, 1 for a contradiction, 2 for insufficient evidence
(including older run starts without a plan version). It does not grade the agent's prose.

## Check a result

Open `runs/<task_id>/report.md`. It lists planned versus completed runs, the
mean of each metric per configuration, and every run with links to its raw
output and to the source diff it ran with.

Recalculate one run's metrics from its raw output. The script uses only the
Python standard library and none of the harness code:

```bash
python3 scripts/recompute_metric.py runs/<task_id>/raw/interval-30s__seed-1 --nodes 300
```

Its `t90_ms` and `orphan_rate` must equal that run's row in `report.md` and its
entry in `runs/<task_id>/results.json`. For a BlockSim run, leave out
`--nodes`; the script reads `SimOutput.csv` and `Chain.csv` and prints
`stale_rate` and `node0_block_share`.

## What a task directory holds

| Path | Contents |
|---|---|
| `plan.toml`, `plan.json` | the plan file as written (run mode), and the executed plan's canonical form, whose SHA-256 is the plan version |
| `plans/` | every plan version proposed in the task |
| `approvals.jsonl` | every decision, bound to a plan version |
| `trace.jsonl` | every event, with active and waiting time and the stop reason |
| `history.md` | (agent tasks) every message of every context window, with full tool results |
| `figures/` | (agent tasks) each figure the agent drew: PNG, SVG, the script that drew it, its output, and `index.json` with the captions; the report shows them |
| `literature.json`, `papers/` | (agent tasks) searches, found and supplied papers, full texts, PDFs and their parser output, viewed figures |
| `manifest.json` | simulator commit, image ID, command, limits, PDF parses, and task status |
| `results.json`, `report.md` | per-run status and metrics, and the readable report |
| `raw/<run_id>/` | the simulator's own output: `stdout.txt`, `blockList.txt`, `static.json` from SimBlock; `result.xlsx` and one CSV per sheet from BlockSim |
| `changes/<run_id>.diff`, `changes/edits.diff` | the parameter and seed edits applied to each run's source, and the agent's permitted edits |
| `validation.json` | the validation check's runs and verdict, for a plan with permitted edits |
| `sandbox/` | every sandbox exec command and its output |
| `workspace/` | `original/` (the simulator source copied from the image, never changed), `edited/` (the agent's copy), `scratch/` (its builds and tests), and `runs/` (each simulation run's source copy, removed after its output is saved) |

## Develop

```bash
make check         # lint and offline tests; run before every commit
make test-docker   # integration tests against the execution image
make test-live     # the real model APIs and literature services; needs .env
```

| Read | For |
|---|---|
| [AGENTS.md](AGENTS.md) | rules and definitions for changing the repo |
| [docs/README.md](docs/README.md) | the index of all docs |
