from __future__ import annotations

import json

from abc_harness.execution.grounding import check_answer, claims_in, source_text
from abc_harness.execution.trace_check import check_task

HISTORY = """# Conversation history of task t

## Window 1

### user

With 300 nodes, does a 30 s interval produce more orphans?

### assistant

> _thinking (summary):_ The paper says 0.48866, I recall.

I will read the paper. The answer is 0.777.

### tool result: `read_paper` (id `tu_1`)

```text
| 1/3 | $0.337\\,05$ | 0.48866 |
### 6.3. Hyperparameters
The dataset covers 23 million blocks.
```

### assistant

Done.
"""


def task_dir(tmp_path, answer, history=HISTORY, results=None):
    root = tmp_path / "task"
    root.mkdir()
    (root / "history.md").write_text(history, encoding="utf-8")
    report = f"# Report\n\n## Results\n\n| base | 0.2500 |\n\n## Agent summary\n\n{answer}\n\n## Limits\n\n77.7\n"
    (root / "report.md").write_text(report, encoding="utf-8")
    (root / "results.json").write_text(json.dumps(results or []), encoding="utf-8")
    return root


def missing(root):
    return [c.text for c in check_answer(root).ungrounded]


def test_numbers_from_tool_results_the_question_and_tables_are_grounded(tmp_path):
    answer = ("With 300 nodes and a 30 s interval the orphan rate was 0.25 (25%). The paper's optimum is "
              "0.48866 at 1/3 and 0.33705 at α=1/3; the data covers 2300万 blocks, or 23M.")
    root = task_dir(tmp_path, answer)
    assert missing(root) == []
    assert [c.text for c in claims_in(answer)] == ["300", "30", "0.25", "25%", "0.48866", "0.33705", "2300万", "23M"]


def test_the_agents_own_words_are_not_a_source(tmp_path):
    # 0.777 appears only in an assistant turn, so it has no source; 77.7 is in a harness-written report section.
    root = task_dir(tmp_path, "The answer is 0.777, and 77.7 elsewhere; earlier I said 0.48866.")
    assert missing(root) == ["0.777"]
    kept = source_text(HISTORY)
    assert "0.777" not in kept and "I recall" not in kept and "23 million" in kept


def test_unit_changes_and_full_precision_statistics(tmp_path):
    results = [{"run_id": f"base__seed-{i}", "configuration": "base", "status": "completed",
                "metrics": {"orphan_rate": v, "t90_ms": 21412.0}} for i, v in enumerate([0.0, 0.0099, 0.0])]
    # The mean 0.0033 is not printed anywhere at that precision; t90 21412 ms is stated in seconds.
    root = task_dir(tmp_path, "Mean orphan rate 0.0033, t90 21.4 s, about 0.99% at worst; 150 times higher.",
                    results=results)
    assert missing(root) == ["150"]  # a ratio the agent computed has no source


def test_code_spans_paths_and_single_digits_are_not_checked(tmp_path):
    root = task_dir(tmp_path, "Plan `cba63cf1…030a` ran 3 seeds; see `task/figures/fig-2026.png` and [x](a/9999).")
    assert check_answer(root).checked == []


def test_trace_check_reports_ungrounded_numbers_as_a_warning_without_failing(tmp_path):
    root = task_dir(tmp_path, "The orphan rate was 0.25, and 0.913 in the slow case.")
    (root / "trace.jsonl").write_text("", encoding="utf-8")
    _code, lines = check_task(root)
    assert "WARN: report.md Agent summary: no source for 0.913 (derived by the agent, or unsupported; check them)" \
        in lines
    assert "NOTE: report.md Agent summary: 1 of 2 numbers found in the task's sources" in lines
    assert not any(line.startswith("FAIL") and "summary" in line for line in lines)


def test_numbers_formatted_as_code_are_still_checked(tmp_path):
    root = task_dir(tmp_path, "Mean `0.6000` (SD `0.0700 ± 0.01`), version `6dca409e`, file `run-2026.csv`.")
    checked = [c.text for c in check_answer(root).checked]
    assert checked == ["0.6000", "0.0700", "0.01"]
