"""Grounded numbers: does every number in the agent's final answer appear in what the task saw or produced?

The final answer is `answer.md` (in tasks from before it existed, the "Agent summary" section of `report.md`). Its sources are what the harness or the
outside world wrote, never the agent's own words: tool results and the researcher's messages in
`history.md` (assistant turns, the model's window summaries, and earlier final answers are left out), the
plan, `results.json`, `validation.json`, and `report.md` without the summary.

Each configuration's mean and sample standard deviation of every metric are sources too, at full precision,
since the report's tables round them. A number in the answer is grounded when some source number rounds to it
at the answer's precision, directly or after the usual unit changes: a fraction stated as a percentage (0.0932
as 9.3%), a factor of 1000 (21412 ms as 21.4 s), and a count written in words or Chinese units ("23 million"
as 2300万). LaTeX thin spaces inside a number (`0.337\\,05`) are ignored. One-digit integers are not checked,
nor anything inside `code` spans (plan versions, paths, file names) except a span that holds only numbers,
such as `0.0245` or `0.0245 ± 0.0016`: some models format their results that way. The check is a heuristic: a number the agent derived itself, such as a standard error it
computed, has no source and is reported, and a small integer may find a source by coincidence. So an
ungrounded number is a warning for the researcher, not a failed check.
"""

from __future__ import annotations

import bisect
import json
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from abc_harness.execution.report import ANSWER_FILE

SUMMARY_HEADING = "## Agent summary"
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?"
                     r"(\s?%|\s?[万亿]|[kKM](?![A-Za-z])|\s(?:thousand|million|billion)\b)?")
_SCALE = {"k": 1e3, "K": 1e3, "M": 1e6, "thousand": 1e3, "million": 1e6, "billion": 1e9, "万": 1e4, "亿": 1e8}
_THIN_SPACE = re.compile(r"(?<=\d)(?:\\[,;:! ]|\{,\}|[\u2009\u202f])(?=\d)")
_CODE = re.compile(r"```.*?```|`[^`\n]*`", re.DOTALL)
_NUMBERS_ONLY = re.compile(r"[\s\d.,%±+\-−]*\d[\s\d.,%±+\-−]*")  # a code span that is a result, not a path or id
_LINK_TARGET = re.compile(r"\]\([^)]*\)")
# history.md sections the harness starts; anything else inside a section belongs to it.
_TOOL_SECTION = re.compile(r"^### tool (result|error): `[^`]*` \(id `[^`]*`\)$")
_USER_SECTION = re.compile(r"^### user( \(.*\))?$")
_MODEL_WRITTEN = ("## Summary of the earlier window (written by the model)", "Your final answer then:")


@dataclass(frozen=True)
class Claim:
    text: str
    value: float
    decimals: int
    percent: bool


@dataclass(frozen=True)
class Grounding:
    checked: list[Claim]
    ungrounded: list[Claim]


def check_answer(root: Path) -> Grounding | None:
    """The answer's numbers and which of them no source supports; None when the task has no final answer."""
    report_path = root / "report.md"
    if not report_path.exists():
        return None
    report = report_path.read_text(encoding="utf-8")
    answer, rest = final_answer(root, report)
    if not answer.strip():
        return None
    texts = [rest, *(_read(root / name) for name in ("plan.json", "results.json", "validation.json"))]
    history = root / "history.md"
    if history.exists():
        texts.append(source_text(history.read_text(encoding="utf-8")))
    sources = sorted({v for text in texts for v in numbers_in(text)} | set(_summary_statistics(root)))
    claims = claims_in(answer)
    return Grounding(claims, [c for c in claims if not grounded(c, sources)])


def final_answer(root: Path, report: str) -> tuple[str, str]:
    """(the agent's final answer, the report without it).

    The answer is answer.md. A task from before answer.md existed falls back to split_summary, which cannot
    tell where an answer with its own level-two heading ends.
    """
    path = root / ANSWER_FILE
    if not path.exists():
        return split_summary(report)
    answer = path.read_text(encoding="utf-8").strip()
    return answer, report.replace(answer, "", 1) if answer else report


def split_summary(report: str) -> tuple[str, str]:
    """(the Agent summary section, the report without it)."""
    start = report.find(SUMMARY_HEADING)
    if start < 0:
        return "", report
    end = report.find("\n## ", start + len(SUMMARY_HEADING))
    end = len(report) if end < 0 else end
    return report[start + len(SUMMARY_HEADING):end], report[:start] + report[end:]


def source_text(history: str) -> str:
    """The parts of history.md the agent did not write: tool results and the researcher's messages."""
    kept, keep, skipping_model_text = [], False, False
    for line in history.splitlines():
        if line == "### assistant":
            keep = False
        elif _TOOL_SECTION.match(line) or _USER_SECTION.match(line) or line.startswith("## Window "):
            keep, skipping_model_text = True, False
        elif keep and line.startswith(_MODEL_WRITTEN):
            skipping_model_text = True
        elif skipping_model_text and line.startswith(("## ", "### ")):
            skipping_model_text = False
        if keep and not skipping_model_text:
            kept.append(line)
    return "\n".join(kept)


def _code_span(match: re.Match[str]) -> str:
    inner = match.group(0).strip("`")
    return f" {inner} " if not match.group(0).startswith("```") and _NUMBERS_ONLY.fullmatch(inner) else " "


def claims_in(answer: str) -> list[Claim]:
    text = _THIN_SPACE.sub("", _LINK_TARGET.sub("]", _CODE.sub(_code_span, answer)))
    claims = []
    for m in _NUMBER.finditer(text):
        whole, fraction, suffix = m.group(1), m.group(2) or "", (m.group(3) or "").strip()
        if not fraction and not suffix and len(whole) == 1:
            continue
        scale = _SCALE.get(suffix, 1)
        decimals = (len(fraction) - 1 if fraction else 0) - round(len(str(int(scale))) - 1)
        # "275K" claims 275,000 to the nearest thousand; "2300万" 23,000,000 to the nearest 10,000
        claims.append(Claim(m.group(0).strip(), float(whole.replace(",", "") + fraction) * scale, decimals,
                            suffix == "%"))  # fmt: skip
    return claims


def numbers_in(text: str) -> list[float]:
    """Every number in a source, and its scaled value when a word or unit follows it ("23 million")."""
    values = []
    for m in _NUMBER.finditer(_THIN_SPACE.sub("", text)):
        value = float(m.group(1).replace(",", "") + (m.group(2) or ""))
        values.append(value)
        scale = _SCALE.get((m.group(3) or "").strip())
        if scale:
            values.append(value * scale)
    return values


def _summary_statistics(root: Path) -> list[float]:
    """Each configuration's mean and sample standard deviation of each metric, from results.json."""
    try:
        records = json.loads((root / "results.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    by_metric: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in records if isinstance(records, list) else []:
        if r.get("status") != "completed":
            continue
        for name, value in (r.get("metrics") or {}).items():
            if isinstance(value, int | float):
                by_metric[(str(r.get("configuration")), name)].append(float(value))
    stats = []
    for values in by_metric.values():
        stats.append(statistics.fmean(values))
        if len(values) > 1:
            stats.append(statistics.stdev(values))
    return stats


def grounded(claim: Claim, sources: list[float]) -> bool:
    """True when a source number rounds to the claim, directly or after a unit change."""
    factors = (1, 100) if claim.percent else (1, 1000, 0.001)
    half_step = 0.5 * 10.0 ** -claim.decimals
    for factor in factors:
        target, tolerance = claim.value / factor, half_step / factor * (1 + 1e-9)
        i = bisect.bisect_left(sources, target - tolerance)
        if i < len(sources) and sources[i] <= target + tolerance:
            return True
    return False


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""
