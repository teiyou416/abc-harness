"""arXiv full text as plain lines, from arXiv's HTML rendering of the paper source.

arXiv serves an HTML version of most papers (arxiv.org/html/<id>, with
ar5iv.labs.arxiv.org as the fallback for older ones). Both use LaTeXML markup,
so one parser covers them. Headings become lines starting with `#`, math keeps
its LaTeX source, tables become Markdown rows, and page furniture (navigation,
scripts, buttons) is dropped. Figures are listed with their caption and image
URLs, so the agent can view them one at a time.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urljoin

from abc_harness.literature.figures import Figure, label_from_caption

HTML_URLS = ("https://arxiv.org/html/{id}", "https://ar5iv.labs.arxiv.org/html/{id}")
SKIP = {"script", "style", "nav", "header", "footer", "button", "noscript", "svg", "form"}
BLOCK = {"p", "div", "li", "tr", "figcaption", "caption", "blockquote", "section", "article", "dt", "dd", "br",
         "h1", "h2", "h3", "h4", "h5", "h6", "table"}  # fmt: skip


class _Text(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.lines: list[str] = []
        self.current: list[str] = []
        self.skip = 0
        self.math = 0
        self.heading = 0
        self.figures: list[Figure] = []
        self.figure: Figure | None = None  # the figure being read, if any
        self.figure_depth = 0
        self.in_caption = False
        self.row: list[str] | None = None  # cells of the table row being read
        self.rows_in_table = 0
        self.equation = False  # LaTeXML lays out display equations as tables; keep them as plain lines

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.skip or self.math:
            if tag in SKIP:
                self.skip += 1
            if tag == "math":
                self.math += 1
            return
        if tag in SKIP:
            self.skip = 1
            return
        if tag == "math":
            alt = dict(attrs).get("alttext") or ""
            self.current.append(f" ${alt}$ " if alt else " ")
            self.math = 1
            return
        attributes = dict(attrs)
        if tag == "figure":
            classes = attributes.get("class") or ""
            if self.figure is None and "ltx_figure" in classes and "ltx_table" not in classes:
                self.figure, self.figure_depth = Figure(label="", caption=""), 0
            if self.figure is not None:
                self.figure_depth += 1
        if tag == "img" and self.figure is not None and attributes.get("src"):
            self.figure.images.append(urljoin(self.base_url, attributes["src"] or ""))
        if tag == "table":
            self.rows_in_table = 0
            self.equation = "ltx_eqn" in (attributes.get("class") or "")
        if tag == "tr":
            self._flush()
            self.row = []
            return
        if tag in {"td", "th"} and self.row is not None:
            self._end_cell()
            return
        if tag in BLOCK:
            self._flush()
        if tag == "figcaption":
            self.in_caption = True
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading = int(tag[1])

    def handle_endtag(self, tag: str) -> None:
        if self.skip:
            if tag in SKIP:
                self.skip -= 1
            return
        if self.math:
            if tag == "math":
                self.math -= 1
            return
        if tag in {"td", "th"} and self.row is not None:
            self._end_cell()
            return
        if tag == "tr" and self.row is not None:
            self._end_cell()
            cells, self.row = self.row, None
            if any(cells) and self.equation:
                self.lines.append(" ".join(c for c in cells if c).replace("\\|", "|"))
            elif any(cells):
                self.lines.append("| " + " | ".join(cells) + " |")
                self.rows_in_table += 1
                if self.rows_in_table == 1 and not self.equation:
                    self.lines.append("|" + "---|" * len(cells))
            return
        if tag in BLOCK:
            self._flush()
        if tag == "figcaption" and self.figure is not None:
            self.in_caption = False
            if not self.figure.caption and self.lines:
                self.figure.caption = self.lines[-1]
                self.figure.line = len(self.lines)
        if tag == "figure" and self.figure is not None:
            self.figure_depth -= 1
            if self.figure_depth == 0:
                if self.figure.images:
                    self.figure.label = label_from_caption(self.figure.caption, len(self.figures) + 1)
                    self.figures.append(self.figure)
                self.figure = None

    def handle_data(self, data: str) -> None:
        if not self.skip and not self.math:
            self.current.append(data)

    def _end_cell(self) -> None:
        if self.row is not None:
            text = re.sub(r"\s+", " ", "".join(self.current)).strip()
            self.current = []
            if text or self.row:
                self.row.append(text.replace("|", "\\|"))

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.current)).strip()
        self.current = []
        if text:
            self.lines.append(("#" * self.heading + " " + text) if self.heading else text)
        self.heading = 0


def parse(html: str, base_url: str) -> tuple[list[str], list[Figure]]:
    """Text lines and the figures of an arXiv HTML page; image URLs are resolved against `base_url`."""
    parser = _Text(base_url)
    parser.feed(html)
    parser.close()
    parser._flush()
    figures = [f for f in parser.figures if f.label]
    return parser.lines, figures


def html_to_lines(html: str) -> list[str]:
    return parse(html, "https://arxiv.org/html/")[0]


def outline(lines: list[str]) -> list[str]:
    """Heading lines with their 1-based line numbers, for paging with read_file."""
    return [f"line {i}: {line}" for i, line in enumerate(lines, start=1) if line.startswith("#")]
