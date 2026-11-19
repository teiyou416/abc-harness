# ABC Harness

ABC Harness is a local CLI that turns a researcher's question into a
reproducible blockchain simulation. The researcher reviews an experiment plan
and approves it. The harness then runs the simulator in a Docker container and
writes a report linked to the raw output.

The harness runs a hand-written SimBlock or BlockSim plan after approval,
and an agent drafts plans from a research question (milestone M2).
[docs/status.md](docs/status.md) says what works today.

## Requirements

- macOS on Apple silicon (other platforms are untested)
- [uv](https://docs.astral.sh/uv/)
- Docker Desktop or another Docker-compatible runtime, running
- Network access for the first `uv sync` and the image build

## Run the SimBlock example

These are the commands used to produce the M1 example run.

```bash
uv sync
uv run abc-harness image build
uv run abc-harness run examples/simblock-baseline.toml
```

`image build` creates three images (about 4 GB in all; build one with `--only`):

- `abc-harness-sim:simblock-8a1285a`: SimBlock at commit
  `8a1285aa37b832385b0be2ae6f804885a4a7031f` with JDK 21.
- `abc-harness-sim:blocksim-603361d`: BlockSim at commit
  `603361dab49101cdd820dbfd86e19536d841cbae` with Python 3.11 and pandas 1.5.3.
- `abc-harness-pdf:mineru-4.2.3`: the PDF parser, MinerU 4.2.3 with its CPU
  models, used to read papers given as PDF. Parsing needs 6 GB of memory, so
  give Docker Desktop at least 8 GB (12 GB to parse beside a simulation).

`uv run abc-harness run examples/blocksim-baseline.toml` runs the BlockSim
example the same way.

`run` prints the plan and asks `Approve this plan? [approve/reject]:`.

- Answer `approve` to run the 10 simulation runs (about 30 seconds). The
  command prints `Artifacts: runs/<task_id>`.
- Answer `reject` to stop. The command prints `No simulator was started.` and
  still writes the decision, the trace and a report.

## Ask the agent

Copy `.env.example` to `.env` and set `ANTHROPIC_API_KEY`. The harness reads
the key from this file and passes it only to the Claude client; it never
enters a container, a trace, or git.

```bash
cp .env.example .env   # then edit .env
uv run abc-harness ask "With 300 nodes, does a 30 s block interval produce more orphans than 600 s?"
```

The agent may ask clarification questions, then shows a plan and asks
`Approve this plan? [approve/revise/reject]:`. Choose `revise` to send it
back with a comment; every new version needs a fresh approval. After the run,
the command prints the agent's summary and the artifact directory.

To have the agent read a paper you choose, pass the PDF; repeat `--paper` for
several. The harness parses each one before the agent starts (1 to 6 minutes
for a 20-page paper, not counted toward the 30-minute limit, and cached for
the next task), and the agent can cite them:

```bash
uv run abc-harness ask "Reproduce Figure 2 of this paper." --paper ~/papers/selfish-mining.pdf
```

`uv run abc-harness trace summary runs/<task_id>` counts the task's model
calls, tokens, tool calls, and errors.

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
| `history.md` | (`ask` only) every message of every context window, with full tool results |
| `literature.json`, `papers/` | (`ask` only) searches, found and supplied papers, full texts, PDFs and their parser output, viewed figures |
| `manifest.json` | simulator commit, image ID, command, limits, PDF parses, and task status |
| `results.json`, `report.md` | per-run status and metrics, and the readable report |
| `raw/<run_id>/` | the simulator's own output: `stdout.txt`, `blockList.txt`, `static.json` from SimBlock; `result.xlsx` and one CSV per sheet from BlockSim |
| `changes/<run_id>.diff` | the parameter and seed edits applied to the simulator source |
| `workspace/source/` | the unmodified simulator source copied from the image |

## Develop

```bash
make check         # lint and offline tests; run before every commit
make test-docker   # integration tests against the execution image
make test-live     # one real Claude API call sequence; needs .env
```

| Read | For |
|---|---|
| [AGENTS.md](AGENTS.md) | rules and definitions for changing the repo |
| [docs/README.md](docs/README.md) | the index of all docs |
