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



def _anchors(doc: Path) -> set[str]:
    """GitHub's heading anchors: lowercase, punctuation dropped, spaces as hyphens."""
    anchors, fenced = set(), False
    for line in doc.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (m := re.match(r"#{1,6} (.+)", line)):
            anchors.add(re.sub(r"[^\w\- ]", "", m.group(1).strip().lower()).replace(" ", "-"))
    return anchors


def test_anchors_resolve():
    broken = []
    for doc in RULEBOOK:
        for target in LINK.findall(doc.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:")) or "#" not in target:
                continue
            file, anchor = target.split("#", 1)
            path = (doc.parent / file).resolve() if file else doc
            if path.suffix == ".md" and path.exists() and anchor not in _anchors(path):
                broken.append(f"{doc.relative_to(ROOT)} -> {target}")
    assert not broken, "links to missing headings:\n" + "\n".join(broken)

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


PACKAGE = ROOT / "src" / "abc_harness"
# Higher layers may import lower ones, never the reverse (docs/architecture.md, "Module map").
LAYERS = {"interfaces": 5, "agent": 4, "tools": 3, "execution": 2, "planning": 1, "literature": 1, "simulators": 0}


def _modules() -> list[Path]:
    return sorted(p for p in PACKAGE.rglob("*.py") if p.name != "__init__.py" or p.parent != PACKAGE)


def _layer(rel_parts: tuple[str, ...]) -> str | None:
    return rel_parts[0].removesuffix(".py") if rel_parts else None


def test_modules_import_only_their_own_or_lower_layers():
    import ast

    upward = []
    for path in _modules():
        own = _layer(path.relative_to(PACKAGE).parts)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("abc_harness"):
                targets = [node.module] if node.module != "abc_harness" else [f"abc_harness.{a.name}" for a in node.names]
            elif isinstance(node, ast.Import):
                targets = [a.name for a in node.names if a.name.startswith("abc_harness")]
            else:
                continue
            for target in targets:
                layer = _layer(tuple(target.split(".")[1:2]))
                if layer in LAYERS and LAYERS[layer] > LAYERS.get(own, 99):
                    upward.append(f"{path.relative_to(PACKAGE)} imports {target}")
    assert not upward, "a lower layer imports a higher one: " + "; ".join(upward)


def test_every_module_is_in_the_module_map():
    text = (DOCS / "architecture.md").read_text(encoding="utf-8")
    section = text.split("## Module map", 1)[1].split("\n## ", 1)[0]
    # Empty __init__.py files only mark a folder as a package; they need no row.
    missing = [str(p.relative_to(PACKAGE)) for p in _modules()
               if p.stat().st_size and f"`{p.relative_to(PACKAGE)}`" not in section]  # fmt: skip
    assert not missing, f"add these modules to the module map in docs/architecture.md: {missing}"
