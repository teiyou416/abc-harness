# Code health review

Reviewed on 2026-11-23 against `c4ab7f547015`. The review covered the 59 Python files under `src/` and checked callers in tests and Docker helpers. The token totals below come from a saved task. The remaining findings follow from reading the source. No failure injection, concurrent-write test, or simulation was performed for this review.

## Highest-priority refactors

### 1. Preserve the boundary between the final answer and its evidence

The report writer inserts the agent's Markdown verbatim under `## Agent summary`. Both the judge and the number checker recover the answer by scanning up to the next level-two heading. If the agent writes a paragraph followed by `## Limitations`, the judge receives only the paragraph and the harness's introductory text. The number checker treats the limitations section as part of the report it can use for corroboration. Ordinary answer formatting can therefore change which claims get reviewed. [report.py:63](../src/abc_harness/execution/report.py#L63) · [grounding.py:61](../src/abc_harness/execution/grounding.py#L61) · [grounding.py:73](../src/abc_harness/execution/grounding.py#L73) · [judge.py:81](../src/abc_harness/agent/judge.py#L81)

Give the judge and number checker an authoritative copy of the final answer with an explicit boundary. Retain a reader for existing task archives. A reviewer can check the proposed design with an answer containing a level-two heading and a number appearing only after that heading. Both consumers should see the full answer, and the number should still require an independent source.

### 2. Separate the shared paper index from the task's literature records

`literature/library.py` spans 515 lines. Its `keep()` method checks eligibility, downloads the PDF, deduplicates it, writes the shared file and index, saves the task's own records, and emits an event. Two CLI processes can read the same old index, add different papers, and overwrite each other's updates. They also use the same `.index.json.part` staging path. A rename makes one write atomic, while the surrounding read-modify-write sequence can still lose an update. [library.py:208](../src/abc_harness/literature/library.py#L208) · [library.py:227](../src/abc_harness/literature/library.py#L227) · [library.py:490](../src/abc_harness/literature/library.py#L490)

`sync_index()` handles a missing index, an I/O error and invalid JSON by starting with an empty dictionary. With PDFs present, the next scan can then replace an unreadable index with filename-derived records. The files survive, but DOI, arXiv ID and originating task metadata can disappear. Give the shared library one owner for index updates, with distinct handling for initial creation and recovery. Review the damaged-index case and two simultaneous saves before optimizing the scan. [library.py:439](../src/abc_harness/literature/library.py#L439)

### 3. Put task setup and teardown under one lifecycle

`execution/task.py` spans 509 lines and owns approvals, execution, validation, PDF caching and final artifacts. Yet the protection around agent-driven tasks begins in another module. After creating the task directory and trace, `run_agent_task()` invokes the start callback, constructs the agent and probes Docker before entering the `try/finally` that calls `task.close()`. For example, a missing Docker executable can raise `FileNotFoundError` during the probe, which catches only `RunnerError`. A task that has already emitted `task_started` can be left without a final report. [task.py:99](../src/abc_harness/execution/task.py#L99) · [loop.py:244](../src/abc_harness/agent/loop.py#L244) · [loop.py:261](../src/abc_harness/agent/loop.py#L261) · [runner.py:90](../src/abc_harness/execution/runner.py#L90)

Protect the interval from task creation through finalization first. Then move PDF parsing and caching behind their own interface. An initialization failure after the trace opens should produce a failed task with an inspectable reason. [task.py:183](../src/abc_harness/execution/task.py#L183) · [task.py:405](../src/abc_harness/execution/task.py#L405)

## Other maintenance findings

| Finding | Evidence and consequence |
|---|---|
| Token totals and cost use different sets of calls | The trace summary counts only `model_call`, while the cost calculation also counts `compaction`. Task `20261121-233655-dc17ae` recorded 56 ordinary calls and one compaction. Line 189 of its local `trace.jsonl` records 40,841 input and 8,390 output tokens for compaction. Those **49,231 tokens** contribute to estimated cost and are absent from the terminal token total. Use one event selection for both totals and keep the breakdown by purpose. [trace.py:55](../src/abc_harness/execution/trace.py#L55) · [console.py:223](../src/abc_harness/interfaces/console.py#L223) · [console.py:295](../src/abc_harness/interfaces/console.py#L295) |
| The paper shelf repeats disk and Docker work | Startup lists the PDFs, then `sync_index()` scans them again and hashes each file. With the parser image available, the per-paper cache lookup inspects the same image and reads each entire file again for the same SHA-256. Reuse the scan's paths and digests and resolve the image once per task. The source establishes the repeated work. Its wall-clock cost has not been measured. [loop.py:254](../src/abc_harness/agent/loop.py#L254) · [loop.py:299](../src/abc_harness/agent/loop.py#L299) · [library.py:454](../src/abc_harness/literature/library.py#L454) · [task.py:173](../src/abc_harness/execution/task.py#L173) |
| A long audit function drops the report's status column | In 74 lines, `_metrics()` checks plan coverage, parses two Markdown tables, recomputes individual metrics and compares grouped results. It extracts detail cells with `r[2:-2]`, dropping the human-readable status. The checker compares trace statuses with JSON separately, so an isolated status typo in the report can pass these checks. Separate the table comparisons by responsibility and verify the displayed status explicitly. [trace_check.py:98](../src/abc_harness/execution/trace_check.py#L98) · [trace_check.py:111](../src/abc_harness/execution/trace_check.py#L111) · [trace_check.py:206](../src/abc_harness/execution/trace_check.py#L206) |
| A failed Docker query can satisfy a cleanup assertion | `running_containers()` calls `docker ps` with `check=False` and uses only stdout. A failed command with empty stdout returns the same empty list the tests expect after cleanup. Check the query's exit status before interpreting the list. [runner.py:219](../src/abc_harness/execution/runner.py#L219) · [test_docker.py:93](../tests/test_docker.py#L93) |
| Two low-priority cleanup candidates | The final return in `human_size()` is unreachable because the loop always returns at its last unit, GB. The one-line `html_to_lines()` wrapper has only a test caller in this repository. Weak variable names were a minor concern compared with the behavior above. [cleanup.py:100](../src/abc_harness/execution/cleanup.py#L100) · [fulltext.py:150](../src/abc_harness/literature/fulltext.py#L150) · [test_literature.py:88](../tests/test_literature.py#L88) |

## Resolution

Handled on branch `feature/code-health`, with a test for each fix:

| Finding | Outcome |
|---|---|
| Answer boundary (1) | Fixed. The final answer is also saved alone as `answer.md`; the judge and the number check read it, and the judge takes its tables from the report without the answer. Older tasks fall back to the heading scan. |
| Task setup outside `try/finally` (3, first part) | Fixed. Agent setup, the parser-image probe, and the library listing run inside the block that ends in `task.close()`. |
| Damaged library index (2, second part) | Fixed. An unreadable `index.json` is moved to `index.json.damaged-<time>` before a new one is written, or left untouched if it cannot be moved. |
| Token totals versus cost | Fixed. Both count `model_call` and `compaction` events; the terminal says how many calls summarized the context. |
| `running_containers()` ignoring failures | Fixed. A failed `docker ps` raises. |
| Unreachable return in `human_size()` | Fixed. |
| Splitting `library.py` and `task.py`; concurrent saves from two processes (2, 3) | Not done. One researcher rarely runs two tasks saving papers at once; revisit if that changes. |
| Repeated library scans and hashing | Not done until measured slow. |
| Status column of the report table | Not done. The table is generated from `results.json`, whose statuses the check already compares with the trace. |
| `html_to_lines()` used only by tests | Not done; harmless. |
