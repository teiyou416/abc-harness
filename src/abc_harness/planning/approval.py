"""Approval records (AGENTS.md hard rule 3).

The harness, not the model, writes every decision to `approvals.jsonl` in the
artifact directory. Code that modifies experiment files or starts a simulator
calls `require_approval` first.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

APPROVALS_FILE = "approvals.jsonl"
DECISIONS = ("approve", "reject", "revise")


class NotApproved(PermissionError):
    """Raised when execution is attempted without approval for the plan version."""


@dataclass(frozen=True)
class Decision:
    plan_version: str
    decision: str
    comment: str = ""
    decided_at: str = ""


def record_decision(artifact_dir: Path, plan_version: str, decision: str, comment: str = "") -> Decision:
    if decision not in DECISIONS:
        raise ValueError(f"unknown decision: {decision}")
    record = Decision(plan_version, decision, comment, datetime.now(UTC).isoformat(timespec="seconds"))
    with (artifact_dir / APPROVALS_FILE).open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
    return record


def read_decisions(artifact_dir: Path) -> list[Decision]:
    path = artifact_dir / APPROVALS_FILE
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [Decision(**json.loads(line)) for line in f if line.strip()]


def require_approval(artifact_dir: Path, plan_version: str) -> None:
    """Raise NotApproved unless the latest decision approves exactly this version."""
    decisions = read_decisions(artifact_dir)
    if not decisions:
        raise NotApproved(f"no decision recorded for plan {plan_version[:12]}")
    latest = decisions[-1]
    if latest.plan_version != plan_version or latest.decision != "approve":
        raise NotApproved(
            f"plan {plan_version[:12]} is not approved (latest decision: {latest.decision} "
            f"for {latest.plan_version[:12]})"
        )
