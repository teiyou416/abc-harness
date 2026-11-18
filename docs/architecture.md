# Architecture

This page describes the system shown in [architecture.png](architecture.png),
which parts the first release builds, and which module holds each part. The
diagram shows the long-term design. The table below is authoritative where the
two differ.

Most modules do not exist yet. A module marked _planned_ names where the code
will go; replace the mark when the module lands.

## Data flow

1. The CLI creates a task, its artifact directory, and its trace.
2. The agent loop sends the system prompt, the researcher's request, and the
   conversation to the model.
3. The model requests a tool. The harness checks the request against the
   limits and the approval state, executes it, writes a trace event, and
   returns the result to the model.
4. The model drafts a plan. The Human Interaction tool shows it to the
   researcher, and the harness records the decision for that plan version.
5. After approval, the runner executes simulation runs in the execution image.
   The report step matches planned runs against completed runs and computes
   metrics from raw output.
6. The loop ends when the model finishes, the researcher rejects the plan, or a
   limit stops the task. The harness writes the report and manifest in every
   case.

## Diagram boxes in the first release

| Diagram element | First release | Module |
|---|---|---|
| Loop (LLM, tool calls, end-loop guardrails) | Yes. One loop; guardrails enforce the time, call, and context limits. | `loop.py`, `limits.py` _planned_ |
| Tools: Files | Yes. Reads anywhere in the repository and task; writes only inside the task workspace and permitted files. | `tools/files.py` _planned_ |
| Tools: Execution (Bash) | Replaced by the runner and sandbox exec, both inside the execution image. No general shell on the host. | `runner.py`, `tools/sandbox.py` _planned_ |
| Tools: Web Retrieval | Yes. Sources are listed in the project specification. | `tools/literature.py` _planned_ |
| Tools: Human Interaction | Yes, for clarification and plan review. The harness, not the model, records approval. | `tools/human.py`, `approval.py` _planned_ |
| Tools: Custom Tools | Later | |
| Simulators: SimBlock, BlockSim | Yes | `simulators/simblock.py`, `simulators/blocksim.py` _planned_ |
| Simulators: Blockemulator | Later | |
| Literature boxes | Partial. Papers With Code is gone; IEEE Xplore needs its own API key and is optional. | `tools/literature.py` _planned_ |
| System prompt, user prompt, working memory | Yes, with a single system prompt file. | `prompts/system.md` _planned_ |
| SOUL.md, SKILL.md, History.md | Later. `trace.jsonl` and the artifact directory are the record of a task. | |
| Context summarization and token caps | Partial. A hard context limit stops the task with a recorded reason. Summarization waits until traces show the need. | `limits.py` _planned_ |
| Draft | Yes. The draft is the structured plan shown for review. | `plan.py` _planned_ |
| LLM Ops: trace | Yes. One `trace.jsonl` per task and a CLI summary of calls, tokens, latency, and errors. | `trace.py` _planned_ |
| LLM Ops: LLM-as-a-judge, Diagnose, Gate, Release | Later. Result verification is deterministic. | |

All module paths are relative to `src/abc_harness/`.

## Execution environment

- `docker/Dockerfile` builds the execution image for arm64. It installs SimBlock
  and BlockSim at pinned commits with their build and runtime dependencies. Each
  task manifest records the image digest and simulator commits.
- The harness and the model client run on the host. The API key never enters a
  container, and containers receive only allowlisted environment variables.
- At task start, the harness copies the simulator source from the image into the
  task workspace and mounts only that directory into containers.
- Containers run with `--network none`, CPU and memory limits, and a task label.
  On a timeout or limit, the harness stops and removes every container with that
  label.
- Nothing is installed at runtime. A new dependency means a new image, which
  requires a new plan version and fresh approval.
