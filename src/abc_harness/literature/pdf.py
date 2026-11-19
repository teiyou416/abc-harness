"""Full text from a PDF, as parsed by MinerU in its own container (the PDF parser image).

The literature layer does not start containers. It receives a `PdfConvert`
callable from the task, which runs the parser image on one PDF and leaves
MinerU's output in a directory. This module turns that output,
`structured_content.json` plus cropped images, into the same text lines and
figure list that `fulltext.py` makes from arXiv HTML, so the agent reads both
the same way.

What MinerU recognizes is not exact. Body text matched arXiv HTML for 96-98%
of sentences in our tests, but tables lost decimal points ("0 370 77" for
0.37077). Every saved text therefore starts with a note that says so, every
table is listed as a figure whose image the agent can view, and a quote that
falls inside a table is refused as a citation (see `Library.in_pdf_table`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from abc_harness.literature.figures import Figure, label_from_caption

PARSER_IMAGE = "abc-harness-pdf:mineru-4.2.3"
PARSE_TIMEOUT_SECONDS = 15 * 60
OUTPUT_FILE = "structured_content.json"
ARXIV_PDF_URL = "https://arxiv.org/pdf/{id}"

# Page furniture, not paper text.
SKIP_BLOCKS = {"header", "footer", "page_number", "aside_text"}
FIGURE_BLOCKS = {"image", "chart"}
NOTE = ("# Note: machine-recognized from the PDF by MinerU. Text, formulas and tables may contain errors; table "
        "numbers may be wrong (for example lost decimal points). View a table with view_figure before using a "
        "value from it, and cite such values as figure readings, not quotes.")  # fmt: skip
TABLE_WARNING = "[Table recognized from the PDF; its numbers may be wrong. View it with view_figure before use.]"


class PdfError(Exception):
    """The PDF could not be parsed: no parser image, a timeout, a crash, or unreadable output."""


@dataclass(frozen=True)
class ParseInfo:
    """How one PDF was parsed. `seconds` is the parser's own run time, also when the result came from cache."""

    image_id: str
    revision: str
    seconds: float
    cached: bool
    pdf_sha256: str


class PdfConvert(Protocol):
    """Parse `pdf` into `out_dir` (which receives OUTPUT_FILE and `images/`). Raises PdfError."""

    def __call__(self, pdf: Path, out_dir: Path) -> ParseInfo: ...


@dataclass
class ParsedPdf:
    lines: list[str]
    figures: list[Figure]  # figures and tables, each with the path of its cropped image in the task
    title: str
    abstract: str


def parse_structured(data: dict[str, Any], image_dir: str) -> ParsedPdf:
    """Text lines, figures, title and abstract from MinerU's structured output.

    `image_dir` is the task-relative directory MinerU's `images/...` paths are relative to. Headings
    become `#` lines, display equations `$$ ... $$` lines, and tables Markdown rows after a warning line.
    A paragraph that MinerU marks as continuing from the previous column or page is joined to the text it
    continues, also across a figure placed in between, so a quote that crosses the break still matches.
    """
    lines: list[str] = []
    figures: list[Figure] = []
    title = str((data.get("metadata") or {}).get("document", {}).get("title") or "")
    abstract_parts: list[str] = []
    in_abstract = False
    last_text: int | None = None  # index of the last paragraph line, which a continuation joins
    for page in data.get("pages", []):
        for block in page.get("blocks", []):
            kind = block.get("type", "")
            content = _text(block.get("content"))
            if kind in SKIP_BLOCKS:
                continue
            if kind in ("doc_title", "paragraph_title"):
                level = 1 if kind == "doc_title" else max(2, int(block.get("level") or 2))
                if content:
                    lines.append("#" * level + " " + content)
                    title = title or (content if kind == "doc_title" else "")
                    in_abstract = content.strip().lower().rstrip(".:") == "abstract"
                last_text = None
                continue
            if kind == "equation":
                if content:
                    lines.append(f"$$ {content} $$")
                last_text = None
                continue
            if kind in FIGURE_BLOCKS or kind == "table":
                figure = _figure(block, kind, image_dir, len(figures) + 1, lines)
                same = next((f for f in figures if figure and f.label == figure.label), None)
                if same is not None and figure is not None:
                    same.images += figure.images  # panels of one figure, cropped separately
                elif figure is not None:
                    figures.append(figure)
                if kind == "table" and block.get("content"):
                    lines.append(TABLE_WARNING)
                    lines += [row for row in str(block["content"]).splitlines() if row.strip()]
                for note in block.get("footnotes") or []:
                    if _text(note.get("content")):
                        lines.append(_text(note.get("content")))
                continue
            if not content:
                continue
            if block.get("continues_prev") and last_text is not None:
                lines[last_text] = f"{lines[last_text]} {content}"
                continue
            if in_abstract or (not abstract_parts and content.lower().startswith("abstract")):
                abstract_parts.append(content)
            lines.append(content)
            last_text = len(lines) - 1
    return ParsedPdf(lines, figures, title, " ".join(abstract_parts))


def _figure(block: dict[str, Any], kind: str, image_dir: str, index: int, lines: list[str]) -> Figure | None:
    """Add the block's caption to `lines` and return it as a figure, or None if it has no usable image."""
    caption = " ".join(_text(c.get("content")) for c in block.get("captions") or [] if _text(c.get("content")))
    if caption:
        lines.append(caption)
    source = str(block.get("image_source") or "")
    if not source or not _safe_relative(source):
        return None
    if kind == "table":
        match = re.match(r"^\s*Table\s*(\d+[a-z]?)", caption, re.IGNORECASE)
        label = f"Table {match.group(1)}" if match else f"Table (unnumbered {index})"
    else:
        label = label_from_caption(caption, index)
    # The caption's line, or for a figure without caption the line it follows.
    return Figure(label=label, caption=caption or "(no caption)", images=[f"{image_dir}/{source}"],
                  line=len(lines))  # fmt: skip


def _text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _safe_relative(path: str) -> bool:
    """MinerU output is untrusted: an image path must stay inside its output directory."""
    p = Path(path)
    return not p.is_absolute() and ".." not in p.parts


def figure_images(data: dict[str, Any]) -> set[str]:
    """The image paths of figures and tables; MinerU also crops every equation, which the harness drops."""
    return {str(b["image_source"]) for page in data.get("pages", []) for b in page.get("blocks", [])
            if b.get("type") in FIGURE_BLOCKS | {"table"} and b.get("image_source")}  # fmt: skip


def is_table_line(line: str) -> bool:
    return line.startswith("|") or line.lstrip().lower().startswith("<table") or line == TABLE_WARNING
