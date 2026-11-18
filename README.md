# ABC Harness

ABC Harness is a local CLI that turns a researcher's question into a
reproducible blockchain simulation. The researcher reviews an experiment plan
and approves it. The harness then runs the simulator in a Docker container and
writes a report linked to the raw output.

Milestone M1 is in place: the harness runs a hand-written SimBlock plan after
approval. The agent loop that drafts plans arrives in M2.
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

`image build` creates `abc-harness-sim:simblock-8a1285a`, which contains
SimBlock at commit `8a1285aa37b832385b0be2ae6f804885a4a7031f` and JDK 21.

`run` prints the plan and asks `Approve this plan? [approve/reject]:`.

- Answer `approve` to run the 10 simulation runs (about 30 seconds). The
  command prints `Artifacts: runs/<task_id>`.
- Answer `reject` to stop. The command prints `No simulator was started.` and
  still writes the decision, the trace and a report.

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
entry in `runs/<task_id>/results.json`.

## What a task directory holds

| Path | Contents |
|---|---|
| `plan.toml`, `plan.json` | the plan as written, and the canonical form whose SHA-256 is the plan version |
| `approvals.jsonl` | every decision, bound to a plan version |
| `trace.jsonl` | every event, with active and waiting time and the stop reason |
| `manifest.json` | simulator commit, image ID, command, limits, and task status |
| `results.json`, `report.md` | per-run status and metrics, and the readable report |
| `raw/<run_id>/` | `stdout.txt`, `stderr.txt`, `blockList.txt`, `static.json` from SimBlock |
| `changes/<run_id>.diff` | the parameter and seed edits applied to the SimBlock source |
| `workspace/source/` | the unmodified SimBlock source copied from the image |

## Develop

```bash
make check         # lint and offline tests; run before every commit
make test-docker   # integration tests against the execution image
```

| Read | For |
|---|---|
| [AGENTS.md](AGENTS.md) | rules and definitions for changing the repo |
| [docs/README.md](docs/README.md) | the index of all docs |
