"""The rulebook stays short, linked, and indexed.

AGENTS.md is the first file every contributor and coding agent reads. These
checks keep its caps and links true, as docs/context/conventions.md section 7
requires."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
RULEBOOK = [ROOT / "README.md", ROOT / "AGENTS.md", *sorted(DOCS.rglob("*.md"))]
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
GOTCHA = re.compile(r"^- \*\*\[\d{4}-\d{2}-\d{2}\] .+_Retire when: .+_$")


def _local_links(doc: Path) -> list[str]:
    targets = LINK.findall(doc.read_text(encoding="utf-8"))
    return [t for t in targets if not t.startswith(("http://", "https://", "mailto:", "#"))]


def test_agents_md_fits_its_cap():
    lines = (ROOT / "AGENTS.md").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 100, f"AGENTS.md is {len(lines)} lines; push detail into docs/context/"


def test_status_md_fits_its_cap():
    lines = (DOCS / "status.md").read_text(encoding="utf-8").splitlines()
    assert len(lines) <= 120, f"docs/status.md is {len(lines)} lines; rewrite it shorter"


def test_relative_links_resolve():
    broken = []
    for doc in RULEBOOK:
        for target in _local_links(doc):
            path = (doc.parent / target.split("#", 1)[0]).resolve()
            if not path.exists():
                broken.append(f"{doc.relative_to(ROOT)} -> {target}")
    assert not broken, "broken links:\n" + "\n".join(broken)


def test_every_doc_is_indexed():
    index = DOCS / "README.md"
    linked = {(DOCS / t.split("#", 1)[0]).resolve() for t in _local_links(index)}
    docs = [p for p in DOCS.rglob("*") if p.is_file() and p != index and p.suffix in {".md", ".png"}]
    missing = [str(p.relative_to(ROOT)) for p in docs if p.resolve() not in linked]
    assert not missing, "add these to docs/README.md:\n" + "\n".join(missing)


def test_gotchas_are_dated_and_retirable():
    lines = (DOCS / "context" / "gotchas.md").read_text(encoding="utf-8").splitlines()
    entries = [line for line in lines if line.startswith("- ")]
    assert len(entries) <= 40, f"gotchas.md has {len(entries)} entries; retire some"
    malformed = [line[:60] for line in entries if not GOTCHA.match(line)]
    assert not malformed, "each gotcha needs a [YYYY-MM-DD] date and a _Retire when: ..._:\n" + "\n".join(malformed)
