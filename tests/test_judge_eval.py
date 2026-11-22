"""The judge evaluation: does the judge agree with the gold labels in tests/fixtures/judge/cases.json?

`make eval-judge` runs the judge on every case (one judgment each, about $0.2 with claude-sonnet-5-5) and
fails when it agrees with fewer than AGREEMENT_FLOOR of the good and bad cases. A good case agrees at a score
of 6 or more, a bad one at 5 or less, the rubric's own bands; grey cases are recorded but not scored. `MODEL=<name>` picks the judge.
Each run's scores go to runs/judge-eval/<time>.json and one line of runs/judge-eval/history.jsonl.

The offline test in this file checks that every case builds into a task directory the judge accepts, so a
broken fixture fails `make check`, not a paid run.
"""

from __future__ import annotations

import json
import os
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pytest

from abc_harness.agent.judge import prepare
from abc_harness.execution.grounding import SUMMARY_HEADING, split_summary
from abc_harness.execution.trace_check import answer_number_lines

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "judge"
AGREEMENT_FLOOR = 0.85
# The rubric's own bands: 6-8 means the main conclusion follows, 3-5 that a central claim goes too far.
GOOD_AT, BAD_AT = 6, 5
NOTE_END = "which is computed from `results.json` and the raw output."  # the end of the report's note on the summary


def load_cases() -> list[dict]:
    return json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))["cases"]


def build_case(case: dict, where: Path) -> Path:
    """The case as a finished task directory: a copy of the real task with its answer changed, or a synthetic one."""
    task = where / case["id"]
    if case["kind"] == "synthetic":
        _synthetic(case, task)
        return task
    shutil.copytree(FIXTURES / "real" / case["task"], task)
    if case["kind"] == "mutation":
        report = (task / "report.md").read_text(encoding="utf-8")
        answer, _ = split_summary(report)
        if "answer" in case:  # the whole answer replaced; the harness's note above it stays
            head = answer[: answer.index(NOTE_END) + len(NOTE_END)] if NOTE_END in answer else ""
            new = f"{head}\n\n{case['answer']}\n"
        else:
            new = answer
            for r in case["replace"]:
                assert new.count(r["old"]) == 1, (case["id"], r["old"][:40])
                new = new.replace(r["old"], r["new"])
        (task / "report.md").write_text(report.replace(answer, new), encoding="utf-8")
        # The evidence check the harness would run on the changed answer, not the original one's.
        check = json.loads((task / "trace_check.json").read_text(encoding="utf-8"))
        check["lines"] = [line for line in check["lines"] if "Agent summary" not in line] + case["answer_check"]
        (task / "trace_check.json").write_text(json.dumps(check, ensure_ascii=False), encoding="utf-8")
    return task


def _synthetic(case: dict, task: Path) -> None:
    table = case["table"]
    seeds, completed = table["seeds"], table.get("completed", table["seeds"])
    task.mkdir(parents=True)
    names = [row[0] for row in table["rows"]]
    (task / "manifest.json").write_text(json.dumps({"question": case["question"], "model": "deepseek-flash",
                                                    "status": "completed"}, ensure_ascii=False))
    params = table.get("params") or [{} for _ in names]
    plan = {"title": case["question"], "configurations": [{"name": n, "parameters": v} for n, v in zip(names, params)],
            "seeds": list(range(1, seeds + 1)), "metrics": table["metrics"]}
    if "plan_note" in table:
        plan["notes"] = table["plan_note"]
    (task / "plan.json").write_text(json.dumps(plan, ensure_ascii=False))
    (task / "trace_check.json").write_text(json.dumps({"lines": [
        f"PASS: raw/, results.json and report.md: {completed * len(names) * len(table['metrics'])} measurements checked"]}))
    missing = seeds - completed
    planned = "\n".join(f"| {n} | {seeds} | {completed} | {f'{missing} missing' if missing else '-'} |" for n in names)
    results = "\n".join(f"| {' | '.join(row)} |" for row in table["rows"])
    (task / "report.md").write_text(
        "# Report\n\n## Planned versus completed runs\n\n| Configuration | Planned | Completed | Not completed |\n"
        f"|---|---|---|---|\n{planned}\n\n## Results\n\nEach value is the mean over completed runs, with the sample "
        f"standard deviation and the number of runs.\n\n| Configuration | {' | '.join(table['metrics'])} |\n"
        f"|{'---|' * (len(table['metrics']) + 1)}\n{results}\n\n{SUMMARY_HEADING}\n\n{case['answer']}\n",
        encoding="utf-8")
    check = json.loads((task / "trace_check.json").read_text(encoding="utf-8"))
    check["lines"] += answer_number_lines(task)  # self-contained: the plan, the tables, and the question are its sources
    (task / "trace_check.json").write_text(json.dumps(check, ensure_ascii=False), encoding="utf-8")


def agrees(label: str, score: int | None) -> bool | None:
    if label == "grey" or score is None:
        return None if label == "grey" else False
    return score >= GOOD_AT if label == "good" else score <= BAD_AT


def test_every_gold_case_builds_into_a_task_the_judge_accepts(tmp_path):
    cases = load_cases()
    assert len({c["id"] for c in cases}) == len(cases)
    assert {c["label"] for c in cases} <= {"good", "bad", "grey"} and all(c["reason"] and c["group"] for c in cases)
    for case in cases:
        task = build_case(case, tmp_path)
        prepared = prepare(task)  # raises JudgeRefused for a case the judge would not even look at
        answer = split_summary((task / "report.md").read_text(encoding="utf-8"))[0]
        assert answer.strip() and answer.strip() in prepared.message, case["id"]
        if case["kind"] == "mutation":
            assert "answer_check" in case, case["id"]
            original = split_summary((FIXTURES / "real" / case["task"] / "report.md").read_text(encoding="utf-8"))[0]
            assert answer != original, case["id"]


@pytest.mark.judge_eval
def test_the_judge_agrees_with_the_gold_labels(tmp_path):
    from abc_harness.agent.judge import JUDGE_EFFORT, default_model, judge
    from abc_harness.agent.model import API_KEY_NAMES, make_model
    from abc_harness.agent.secrets import Secrets

    secrets = Secrets.load(ROOT / ".env", names=API_KEY_NAMES)
    name = os.environ.get("JUDGE_EVAL_MODEL") or default_model("deepseek-flash", secrets.has)
    if not name:
        pytest.skip("no judge model key in .env")
    model = make_model(name, JUDGE_EFFORT, lambda key: secrets.get(key) if secrets.has(key) else None)
    rows = []
    for case in load_cases():
        record = judge(prepare(build_case(case, tmp_path)), model)
        rows.append({"id": case["id"], "group": case["group"], "label": case["label"], "score": record["score"],
                     "status": record["status"], "agrees": agrees(case["label"], record["score"]),
                     "reason": record["reason"], "cost": record["estimated_cost"]})
    scored = [r for r in rows if r["agrees"] is not None]
    rate = sum(r["agrees"] for r in scored) / len(scored)
    by_group = defaultdict(list)
    for r in scored:
        by_group[r["group"]].append(r["agrees"])
    group_rate = sum(sum(v) / len(v) for v in by_group.values()) / len(by_group)
    cost: dict[str, float] = defaultdict(float)
    for r in rows:
        for currency, amount in r["cost"].items():
            cost[currency] += amount
    summary = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"), "judge_model": name,
               "agreement": round(rate, 3), "agreement_by_group": round(group_rate, 3), "scored": len(scored),
               "cost": {k: round(v, 4) for k, v in cost.items()}}  # fmt: skip
    out = ROOT / "runs" / "judge-eval"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{summary['ts'].replace(':', '')}.json").write_text(json.dumps({**summary, "cases": rows}, ensure_ascii=False,
                                                                          indent=1))  # fmt: skip
    with (out / "history.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(summary) + "\n")
    print("\n" + "\n".join(f"{r['id']:>8} {r['label']:>5} {r['score']!s:>4} "
                           f"{'ok' if r['agrees'] else ('-' if r['agrees'] is None else 'MISS')}" for r in rows))
    print(json.dumps(summary))
    misses = [f"{r['id']} ({r['label']}, scored {r['score']}): {r['reason']}" for r in scored if not r["agrees"]]
    assert rate >= AGREEMENT_FLOOR, f"agreement {rate:.2f} < {AGREEMENT_FLOOR}:\n" + "\n".join(misses)
