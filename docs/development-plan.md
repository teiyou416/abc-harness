# Development plan

Milestones are ordered by dependency. Each one ends with a demonstration the researcher can run. The [project specification](project-spec.md) defines the terms, rules, and acceptance criteria referenced here.

Every milestone keeps two kinds of tests apart:

- **Test doubles** make logic tests deterministic and fast. Reports and test names must say when a result comes from a double.
- **Real components** (the model, the simulators, literature APIs) are required for the demonstration and acceptance of the milestone.

## M1: SimBlock execution path without an LLM (done 2026-11-19)

The plan is a hand-written file. This milestone proves the approval gate, the runner, and the artifacts before any model is involved.

**What the researcher can do.** Build the execution image, run `abc-harness run examples/simblock-baseline.toml`, review the plan, and approve or reject it. Approval runs SimBlock and prints the artifact directory.

**Delivered**

- `docker/simblock/Dockerfile` and `abc-harness image build`.
- `abc-harness run` with a TOML plan, a content-hash plan version, and approval records.
- Docker runner with per-run source copies, parameter and seed patching from a closed set, per-run timeouts, no network, no host environment, and label-based cleanup.
- The active-runtime limit (30 minutes at first, 2 hours since 2026-11-20), which excludes time spent waiting for the researcher.
- Metrics `t90_ms` and `orphan_rate`, with an independent recalculation script `scripts/recompute_metric.py`.
- `report.md`, `results.json`, `manifest.json`, `trace.jsonl`, raw output, and per-run diffs.
- README steps that reproduce the example.

**Real components:** SimBlock in the execution image.

**Test doubles:** `tests/doubles/fake_runner.py` replaces the Docker runner for approval, status, and limit tests. Docker tests (`make test-docker`) check that containers get no host environment and no network route, that a timeout removes the container, and that a real run matches the recalculation script.

**Acceptance (passed)**

- Approving the plan runs the simulation and prints the artifact directory.
- Rejecting the plan exits without starting a container.
- Following the README reproduces the example, and the recalculation script reproduces a run's metrics from saved raw output.
- `make check` and `make test-docker` pass.

## M2: Agent loop plans a SimBlock experiment (done 2026-11-19)

**What the researcher can do.** Run `abc-harness ask "<question>"`, answer clarification questions, approve, revise, or reject the agent's plan, and read the agent's summary next to the computed results.

**Delivered**

- `agent/loop.py`: one loop over the Claude Messages API with five tools (`describe_simulator`, `read_file`, `ask_researcher`, `propose_plan`, `run_plan`). The harness validates plans, records decisions, and refuses unapproved versions.
- `agent/model.py`: `claude-opus-5-5` at effort `high` by default, with server-side refusal fallback.
- `agent/secrets.py`: API keys from `.env`, passed only to the model client and redacted from traces.
- The 500-call limit and a context limit, checked before every model call.
- A SimBlock capability card (`simulators/simblock_card.md`), ahead of M3.
- `abc-harness trace summary`.

**Real components:** the Claude API and SimBlock.

**Test doubles:** `tests/doubles/scripted_model.py` replays tool calls. `tests/test_live.py` calls the real API and rejects the first plan, so no simulator runs.

**Acceptance**

- The "Plan approval" row with the scripted model: approval runs, rejection ends the task, a revised plan needs fresh approval and the old version is refused.
- The call limit stops a task under a budget of 2, and secrets stay out of traces.
- `make test-live` passes: the real model drafted a valid plan in 2 calls.
- A real `abc-harness ask` run (task `20261119-122555-5402e5`) planned 2 configurations x 10 seeds, ran 20 SimBlock runs, and wrote a summary whose numbers match the Results table and `scripts/recompute_metric.py`. It used 4 model calls and about 16,000 input tokens.

## M2.5: Context management (done 2026-11-19)

**What the researcher can do.** Run long agent tasks without the context growing without bound. Read the archived conversation of a task in `history.md`.

**Scope**

- Split the system prompt into `agent/prompts/SOUL.md` (identity and research values) and `agent/prompts/rules.md` (workflow and tool rules); record both SHA-256 hashes in the manifest.
- Limits: 65,536 output tokens per reply, thinking included (16,384 until 2026-11-19, when a reply with long thinking and a large plan was cut off); compress when the next input would pass 106,496 tokens (soft limit); input plus output never passes 180,224 tokens (hard limit; 131,072 before, raised by the same amount so the input room stayed 114,688); a summary has at most 1,500 words, and its call may reply with up to 32,768 tokens including thinking (8,192 until 2026-11-19); a single tool result has at most 8,192 tokens.
- Compression: archive the window to `history.md` with full tool results, ask the model for a summary of reasoning and open questions, and start a new window with the original question, a task-state block generated by the harness (plan versions, decisions, results, clarification answers), the summary, the latest tool results, and a pointer to `task/history.md`. The summary call counts toward the 500-call limit.
- `read_file` gains `offset` and `limit` so the agent can page through `history.md`.
- Prompt caching for the system prompt and tools.

**Test doubles:** the scripted model with a tiny soft limit.

**Acceptance**

- A task with a small soft limit compresses, archives `Window 1` in `history.md`, and continues.
- The task-state block matches the harness records even when the summary contains a wrong number.
- An oversized tool result is cut to its limit; a task that still exceeds the hard limit after compression stops with reason `context`.
- Changing `SOUL.md` or `rules.md` changes the hashes in the manifest.

All four pass in `tests/test_context.py`. `make test-live` also forces one real compression: the real summary kept to its three sections without numbers or versions, and the agent went on to propose a plan in the new window. Prompt caching now serves the system prompt and tools from cache, leaving 2 to 4 uncached input tokens per call.

## M3: BlockSim and simulator selection (done 2026-11-19)

**What the researcher can do.** Ask a question that either simulator might answer and read why the agent chose one, with entries cited from both capability cards. Run `examples/blocksim-baseline.toml` directly.

**Delivered**

- `docker/blocksim/Dockerfile`: BlockSim at commit `603361d` on Python 3.11 with pandas 1.5.3, plus `xlsx_to_csv.py`. `abc-harness image build` builds both images.
- `simulators/blocksim.py` and `blocksim_card.md`: the Bitcoin model only, with per-miner hash power, a closed parameter set, seeding of `random` and `numpy.random`, and the metrics `stale_rate` and `node0_block_share`. The Ethereum model is not offered.
- The runner now takes the image per call, so one task runs whichever simulator its plan names.
- `scripts/recompute_metric.py` recognises BlockSim output.
- `rules.md`: the agent reads every card before choosing and cites both in the rationale.

**Acceptance (passed)**

- Simulator integration: the real example ran 10 BlockSim runs in 18 seconds. A seed reproduces a run exactly, and the recalculation script matches the harness.
- Simulator selection, with the real model in `make test-live`: a t90 question chose SimBlock and cited BS-N1; a 40% hash-power question chose BlockSim and cited SB-M3 and SB-N3; a selfish-mining question proposed no plan and cited SB-N1 and BS-N2.

**Notes for M6.** BlockSim has no selfish mining (BS-N2), as expected. `node0_block_share` is the reward-share measurement M6 needs once node 0 can run a selfish strategy.

## M4: Literature retrieval (done 2026-11-19)

**What the researcher can do.** Ask a question that needs a reference without supplying one and see each cited source tied to a specific choice in the plan.

**Delivered**

- `literature/`: OpenAlex search (no key) and Semantic Scholar search (optional key in `.env`); the first round covers FC, AFT, and ICBC, and a broadened search covers all venues and preprints. arXiv full text comes from arXiv's HTML rendering, with ar5iv as the fallback. Requests pause per host and retry within the task's remaining time.
- `tools/search_papers.py` and `tools/read_paper.py`. Full texts are saved as `papers/<arxiv_id>.txt`, and the agent pages through them with `read_file`.
- Plans carry `citations` (paper, what it supports, a verbatim quote). The harness refuses a citation unless the paper came from a search in the same task and the quote appears in its abstract or saved full text. The report lists each citation with the place its quote was found; `sources.json` (renamed `literature.json` in M4.1) keeps every search and paper.
- DBLP is dropped: it answers scripts with a bot check. The arXiv search API answered 429 throughout. Both are in `docs/context/gotchas.md`.

**Test doubles:** recorded OpenAlex and arXiv responses in `tests/fixtures/literature/`. The Semantic Scholar response is hand-written from its documented format, because the API refused requests without a key.

**Acceptance (passed)**

- Literature retrieval, with the real model and services in `make test-live`: asked to use the published mean Bitcoin block propagation delay, the agent searched, broadened, read the full text of arXiv 1505.05343, and set `Bdelay` to 12.6 s with the quote "the mean was 12.6 seconds"; it also cited Decker and Wattenhofer (P2P 2013) for propagation delay causing forks. The harness found every quote.

**Not verified yet.** The Semantic Scholar path, including its venue names for FC, AFT, and ICBC, has run only against the hand-written fixture. Check it once a key is in `.env`.

## M4.1: Figures (done 2026-11-19)

**What the researcher can do.** See a plan parameter justified by a value the agent read off a figure, clearly marked as approximate, with the figure image to check it against.

**Delivered**

- `read_paper` lists each figure with its caption; `tools/view_figure.py` shows one figure to the model as an image and saves it under `papers/<arxiv_id>/figures/`. SVG figures are skipped, because the API accepts PNG, JPEG, GIF, and WebP only.
- Tables in the saved full text are Markdown rows, so their numbers can be quoted and checked exactly; display equations stay plain lines.
- A citation is either a quote or a figure reading (`figure`, `reading` with `±`). The harness accepts a figure reading only for a figure viewed in the same task. The review and the report mark it as approximate, and the report links the image.
- Images are estimated by pixel size (about width × height / 750 tokens) instead of base64 length, and a new context window carries no images, only the list of viewed figures.
- `sources.json` is now `literature.json` and the report section is "Citations", following `docs/glossary.md`. The CLI prints the task directory when a task starts.

**Acceptance (passed)**

- With the real model in `make test-live`, the agent found the paper, viewed Figure 1 of arXiv 2007.05614, and read 0.954 ± 0.002 for a point at about 0.954. This is one sample; rerun it when the model or prompt changes.

## M4.2: Papers as PDF (done 2026-11-19)

**What the researcher can do.** Hand the agent the paper to reproduce as a PDF (`ask --paper paper.pdf`), and have the agent read arXiv papers that have no HTML version.

**Delivered**

- `docker/mineru/Dockerfile`: the PDF parser image, MinerU 4.2.3 on CPU ("basic" tier: ONNX models for layout, OCR, formulas, and tables, no VLM), with the models built in. `abc-harness image build` builds it with the simulator images.
- `Task.convert_pdf` runs one container per PDF (no network, 6 CPUs, 6 GB, task label, 15-minute timeout), records the parse in the trace and manifest, and keeps its time out of the active-runtime limit. Parses are cached by PDF content and parser image ID.
- `literature/pdf.py` turns MinerU's `structured_content.json` into the same text lines and figure list as arXiv HTML. Tables are listed as figures, with their cropped image.
- Supplied PDFs are parsed before the first model call and listed in the first message as `local:` papers. `read_paper` falls back to the arXiv PDF when arXiv has no HTML.
- The saved text, `read_paper`, and the report label machine-recognized text. A quote from a PDF table is refused; a table value is cited as a figure reading after viewing the table.

**Feasibility measurements** (2 CPUs unless noted)

- 17-page arXiv 1311.0243: 80 s, 3.9 GB peak memory; Eq. 8 recognized exactly.
- 19-page arXiv 2007.05614: 343 s with 2 CPUs and 155 s with 8 CPUs, identical output; 4.2 to 4.9 GB. Formula recognition (361 formulas) took most of the time.
- Against arXiv HTML, 96% and 98% of body sentences matched exactly once citation styles were ignored. Table 1 lost its decimal points ("0 370 77"); its cropped image is exact.
- The "flash" tier (text layer only) took 9 s but matched 72% of sentences and recognized no formulas, so it is not used.

**Acceptance (passed offline and with Docker)**

- `tests/test_pdf.py`: supplied PDFs are cited, table quotes are refused, parse failures end the task, parse time is excluded, and the cache is reused. `tests/test_docker.py` parses a hand-written PDF with the real image and checks the timeout cleanup.
- With the real model (2026-11-19 and 2026-11-20): Claude Opus 5.5, Claude Sonnet 5.5, and both DeepSeek models read `thesis/common_anchestor.pdf`. In task `20261119-225238-2fe4d9` (`deepseek-flash`), all 14 citations of the plan came from the supplied paper, the report labelled each quote as machine-recognized, and two were figure readings of its Figure 5. No table value has been cited from a real PDF yet.

## M5: Agent-written code in the task workspace (done 2026-11-19)

**What the researcher can do.** Approve a plan that adds a capability to a simulator and receive the diff, validation result, and exportable source.

**Delivered**

- Plans carry `permitted_edits` (path and purpose), a `validation` check (parameters, seeds, one metric, expected value, tolerance), and `edits: false` on configurations that run the original source. The review shows all three.
- `tools/write_file.py` and `tools/edit_file.py` write only the permitted files, or files under `scratch/`, and only after approval. `read_file` reads and lists the original source at `source/<simulator>/`, before approval too.
- `tools/run_command.py` is sandbox exec: the edited source is read-only at `/work/src` and `scratch/` is writable; no network, no host environment; each command and its output go to `sandbox/` and the trace, and its time counts toward the limit.
- At `run_plan` the harness freezes the edits, refuses a change to any file the plan does not permit, saves `changes/edits.diff`, and runs the validation check on the edited source; a failed check stops the task before any configuration runs. The report has a "Code changes and validation" section.
- `abc-harness export runs/<task_id>` packages the edited source with the plan, diff, validation result, and report. Both capability cards gained a "Where the code is" section.

**Test doubles:** `FakeRunner` gained a sandbox and a hook that shows which source each run received; the scripted model writes inside and outside the permitted files.

**Acceptance (passed)**

- Permitted edits: writes outside the permitted files, before approval, or outside the source tree are refused; a change slipped into the edited source behind the harness's back blocks the run; a failed validation check stops the task before any configuration and the report says why. Docker tests confirm that the sandbox cannot write the source, has no network route, and gets no API key.
- With the real model, real source, and real literature search in `make test-live`, the selfish-mining question now produces a plan instead of a refusal: it permits one file (`Models/Bitcoin/BlockCommit.py`), cites Eyal and Sirer with checked quotes, and validates against their closed form at alpha 0.4 and gamma 0.5 (0.5256 ± 0.02, which a wrong gamma would miss).

**Notes for M6.** The live plan above is a good starting point for the demonstration. The first end-to-end run with the real model was task `20261119-225238-2fe4d9` (`deepseek-flash`, 2026-11-19): it added the L-stubborn attack and a fork-choice rule to BlockSim, passed its validation check (0.4003 against an expected 0.4 ± 0.02, 5 seeds), ran all 8 configurations, and drew the revenue figure.

## M5.1: Working tools (done 2026-11-20)

Tools and controls added while preparing M6, after real tasks showed they were needed.

**What the researcher can do.** Hold a conversation of tasks in the terminal, watch every step live, choose the model, and get result figures.

**Delivered**

- `tools/search_files.py`: lines by regular expression, or files by name, in the simulator source, the example plans, the task directory, and earlier tasks of the same conversation.
- `tools/make_figure.py` and the plot image (`docker/plot/`, matplotlib with the `abcplot` helper): after a plan runs, the agent's script draws a static figure from the results; the agent sees the PNG and can redraw, and the report shows each figure with its caption and script.
- `abc-harness chat` (`interfaces/chat.py`, `agent/session.py`): each request runs as its own task; the next task gets a harness-written account of the earlier ones and can read their files under `previous/`; Ctrl-C stops the running task; `/tasks`, `/paper`, `/model`, and `/new` manage the conversation. The command line moved to `interfaces/`.
- Custom metrics: a plan with permitted edits can define metrics that the edited code prints as `ABC_METRIC <name>=<value>` lines, and built-in metrics are computed only when a plan asks for them.
- Models: the list is fixed to `claude-opus-5-5` (default), `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-fable-5-2`, `deepseek-v4-pro`, and `deepseek-flash`; DeepSeek runs through its Anthropic-compatible API with `DEEPSEEK_API_KEY`.
- The terminal shows the current action (model call, tool, PDF parse, simulation run k/N) in one status line redrawn in place, keeps milestones and errors above it, and ends with run statistics, including a cost estimate at list prices (DeepSeek's off-peak prices by the time of each call).
- The default active-runtime limit is 2 hours instead of 30 minutes.
- Added 2026-11-21: `abc-harness trace check` (`execution/trace_check.py`, `execution/recompute.py`) audits a saved task offline: approval and validation before each run, and raw output against `results.json` and `report.md` (`tests/test_trace_check.py`).
- Added 2026-11-21: each model connection attempt waits at most 5 seconds; transient failures are retried within the remaining task time, and the terminal shows each retry (`tests/test_context.py`).

**Test doubles:** `FakeRunner` gained the plot container and printed custom metrics; the chat loop runs from a scripted input sequence.

**Acceptance (passed)**

- Offline tests cover each item: `tests/test_search_files.py`, `test_figures.py`, `test_chat.py`, `test_metrics.py`, and `test_console.py`. `make test-docker` draws a real figure in the plot image.
- Chat with the real model: a second task answered from the first one's results, with 8,052 of 8,380 input tokens served from the prompt cache.
- Custom metrics fixed a real failure: a task that relabelled `orphan_rate` as the attacker's revenue share failed because the unused `t90_ms` could not be computed.
- DeepSeek with real chat tasks (2026-11-19): 88 `deepseek-flash` calls and 61 `deepseek-v4-pro` calls returned thinking, tool calls, and the cache usage fields the cost estimate reads; `deepseek-v4-pro` averaged about 29 s per call.
- The 30-minute limit stopped two paper reproductions (tasks `20261119-231750-318e68` and `20261120-102217-6a74bc`); the second had completed 132 of 216 runs.

## M6: MVP demonstration

**What the researcher can do.** Compare honest mining and selfish mining across mining-power shares and inspect the measured reward share.

**Scope:** the agent implements the selfish mining strategy if the chosen simulator lacks it, validates it against Eyal and Sirer (2014), and sweeps mining-power shares; the report includes the planned-versus-completed matrix and documents the strategy reference, reward definition, baseline, and simulator assumptions.

**Acceptance:** the "Result verification" and "Controlled stopping" rows, including a deliberately omitted run reported as missing and reward share recalculated from raw output.

**Open decision (2026-11-19).** A task executes at most one plan today: the agent can revise a plan before execution and read results afterwards, but a follow-up experiment needs a new task. Decide during M6 whether one task may execute several plans, each approved separately and sharing the task's limits, if validating the strategy and running the sweep in one task proves necessary.
