"""arXiv full text as plain lines, from arXiv's HTML rendering of the paper source.

arXiv serves an HTML version of most papers (arxiv.org/html/<id>, with
ar5iv.labs.arxiv.org as the fallback for older ones). Both use LaTeXML markup,
so one parser covers them. Headings become lines starting with `#`, math keeps
its LaTeX source, and page furniture (navigation, scripts, buttons) is dropped.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

HTML_URLS = ("https://arxiv.org/html/{id}", "https://ar5iv.labs.arxiv.org/html/{id}")
SKIP = {"script", "style", "nav", "header", "footer", "button", "noscript", "svg", "form"}
BLOCK = {"p", "div", "li", "tr", "figcaption", "caption", "blockquote", "section", "article", "dt", "dd", "br",
         "h1", "h2", "h3", "h4", "h5", "h6", "table"}  # fmt: skip


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.current: list[str] = []
        self.skip = 0
        self.math = 0
        self.heading = 0

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
        if tag in BLOCK:
            self._flush()
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading = int(tag[1])
        if tag in {"td", "th"}:
            self.current.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if self.skip:
            if tag in SKIP:
                self.skip -= 1
            return
        if self.math:
            if tag == "math":
                self.math -= 1
            return
        if tag in BLOCK:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self.skip and not self.math:
            self.current.append(data)

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self.current)).strip()
        self.current = []
        if text:
            self.lines.append(("#" * self.heading + " " + text) if self.heading else text)
        self.heading = 0


def html_to_lines(html: str) -> list[str]:
    parser = _Text()
    parser.feed(html)
    parser.close()
    parser._flush()
    return parser.lines


def outline(lines: list[str]) -> list[str]:
    """Heading lines with their 1-based line numbers, for paging with read_file."""
    return [f"line {i}: {line}" for i, line in enumerate(lines, start=1) if line.startswith("#")]
