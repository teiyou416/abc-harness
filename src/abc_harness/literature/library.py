"""The services a task may search (`Literature`) and the papers one task has found (`Library`).

The library is the only record of what the agent found. It is saved to
`literature.json` after every change, every fetched full text goes to
`papers/<arxiv_id>.txt`, and every figure the agent views goes to
`papers/<arxiv_id>/figures/`. A quote counts only if `locate` finds it in a
found paper, and a figure reading only if the agent viewed that figure.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from abc_harness.literature import fulltext, openalex, semantic_scholar
from abc_harness.literature.figures import EXTENSIONS, Figure, media_type, slug
from abc_harness.literature.http import Fetcher, FetchError, PoliteClient
from abc_harness.literature.papers import Paper, normalize

LITERATURE_FILE = "literature.json"
PAPERS_DIR = "papers"
# First-round venues (docs/project-spec.md, "Literature sources").
VENUES = ("FC", "AFT", "ICBC")
MIN_QUOTE_CHARS = 20
MAX_RESULTS = 10


@dataclass
class Literature:
    """The academic services available to every task. Holds the only copy of the Semantic Scholar key."""

    fetcher: Fetcher
    semantic_scholar_key: str | None = None
    client: PoliteClient = field(init=False)
    clock: Callable[[], float] | None = None
    sleep: Callable[[float], None] | None = None

    def __post_init__(self) -> None:
        extra: dict[str, Any] = {}
        if self.clock:
            extra["clock"] = self.clock
        if self.sleep:
            extra["sleep"] = self.sleep
        self.client = PoliteClient(self.fetcher, **extra)

    @property
    def services(self) -> list[str]:
        return ["openalex", "arxiv_html"] + (["semantic_scholar"] if self.semantic_scholar_key else [])

    def search(self, service: str, query: str, limit: int, venues: list[str] | None, time_left: float) -> list[Paper]:
        if service == "semantic_scholar":
            assert self.semantic_scholar_key
            url = semantic_scholar.search_url(query, limit, venues)
            body = self.client.get(url, time_left, {"x-api-key": self.semantic_scholar_key})
            return semantic_scholar.parse(body, query)
        body = self.client.get(openalex.search_url(query, limit, venues), time_left)
        return openalex.parse(body, query)

    def full_text(self, arxiv_id: str, time_left: float) -> tuple[str, list[str], list[Figure]]:
        """Return (url, lines, figures) of the paper's HTML rendering; raises FetchError if neither host has it."""
        errors = []
        for template in fulltext.HTML_URLS:
            url = template.format(id=arxiv_id)
            try:
                html = self.client.get(url, time_left).decode("utf-8", errors="replace")
            except FetchError as e:
                errors.append(str(e))
                continue
            lines, figures = fulltext.parse(html, url)
            if len(lines) > 20:
                return url, lines, figures
            errors.append(f"{url} held no paper text")
        raise FetchError(fulltext.HTML_URLS[0].format(id=arxiv_id), None, "; ".join(errors))


class Library:
    def __init__(self, artifact_dir: Path, literature: Literature | None = None) -> None:
        self.artifact_dir = artifact_dir
        self.literature = literature
        self.papers: dict[str, Paper] = {}
        self.searches: list[dict[str, Any]] = []
        self.full_texts: dict[str, str] = {}  # paper id -> path relative to the artifact directory
        self.figures: dict[str, list[Figure]] = {}  # paper id -> figures listed in its full text
        self.viewed: dict[str, dict[str, list[str]]] = {}  # paper id -> figure label -> saved image paths

    @classmethod
    def load(cls, artifact_dir: Path) -> Library:
        """Rebuild a task's library from its artifacts, for reports and checks after the task."""
        library = cls(artifact_dir)
        path = artifact_dir / LITERATURE_FILE
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            library.papers = {p["id"]: Paper(**p) for p in data.get("papers", [])}
            library.searches = data.get("searches", [])
            library.full_texts = data.get("full_texts", {})
            library.figures = {k: [Figure(**f) for f in v] for k, v in data.get("figures", {}).items()}
            library.viewed = data.get("viewed", {})
        return library

    def search(self, query: str, broaden: bool, limit: int, time_left: float) -> tuple[list[Paper], list[str]]:
        """Search the first-round venues, or everything when `broaden`. Returns (papers, service errors)."""
        assert self.literature is not None
        limit = max(1, min(limit, MAX_RESULTS))
        venues = None if broaden else list(VENUES)
        if broaden:
            services = ["openalex"] + (["semantic_scholar"] if self.literature.semantic_scholar_key else [])
        else:
            services = ["semantic_scholar" if self.literature.semantic_scholar_key else "openalex"]
        found: list[Paper] = []
        errors: list[str] = []
        for service in services:
            try:
                found += self.literature.search(service, query, limit, venues, time_left)
            except FetchError as e:
                errors.append(f"{service}: {e}")
        results = []
        for paper in found:
            known = self.papers.get(paper.id)
            if known:
                known.queries = sorted(set(known.queries) | set(paper.queries))
                known.abstract = known.abstract or paper.abstract
                paper = known
            else:
                self.papers[paper.id] = paper
            if paper not in results:
                results.append(paper)
        self.searches.append({"query": query, "broaden": broaden, "venues": venues, "services": services,
                              "results": [p.id for p in results], "errors": errors})  # fmt: skip
        self.save()
        return results, errors

    def read(self, paper_id: str, time_left: float) -> tuple[str, list[str]]:
        """Fetch and save a paper's full text. Returns (path relative to the artifact directory, lines)."""
        assert self.literature is not None
        paper = self.papers[paper_id]
        assert paper.arxiv_id
        rel = self.full_texts.get(paper_id)
        if rel is None:
            url, lines, figures = self.literature.full_text(paper.arxiv_id, time_left)
            rel = f"{PAPERS_DIR}/{_file_stem(paper.arxiv_id)}.txt"
            path = self.artifact_dir / rel
            path.parent.mkdir(exist_ok=True)
            path.write_text(f"# Source: {url}\n" + "\n".join(lines) + "\n", encoding="utf-8")
            for figure in figures:
                figure.line += 1  # the saved file starts with the source line
            self.full_texts[paper_id] = rel
            self.figures[paper_id] = figures
            self.save()
        return rel, (self.artifact_dir / rel).read_text(encoding="utf-8").splitlines()

    def figure(self, paper_id: str, label: str) -> Figure | None:
        return next((f for f in self.figures.get(paper_id, []) if f.label.lower() == label.strip().lower()), None)

    def view(self, paper_id: str, label: str, time_left: float) -> tuple[Figure, list[tuple[str, bytes]], list[str]]:
        """Fetch and save a figure's images. Returns (figure, [(saved path, image bytes)], skipped notes).

        Formats the API refuses, such as SVG, are skipped with a note. A figure counts as viewed once at
        least one of its images could be shown.
        """
        assert self.literature is not None
        figure = self.figure(paper_id, label)
        assert figure is not None
        paper = self.papers[paper_id]
        assert paper.arxiv_id
        folder = f"{PAPERS_DIR}/{_file_stem(paper.arxiv_id)}/figures"
        shown: list[tuple[str, bytes]] = []
        skipped: list[str] = []
        saved = self.viewed.get(paper_id, {}).get(figure.label)
        if saved:
            shown = [(rel, (self.artifact_dir / rel).read_bytes()) for rel in saved]
            return figure, shown, skipped
        for number, url in enumerate(figure.images, start=1):
            data = self.literature.client.get(url, time_left)
            kind = media_type(data)
            if kind is None:
                skipped.append(f"{url}: not an image format the model can view (for example SVG)")
                continue
            rel = f"{folder}/{slug(figure.label)}-{number}.{EXTENSIONS[kind]}"
            (self.artifact_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.artifact_dir / rel).write_bytes(data)
            shown.append((rel, data))
        if shown:
            self.viewed.setdefault(paper_id, {})[figure.label] = [rel for rel, _ in shown]
            self.save()
        return figure, shown, skipped

    def locate(self, paper_id: str, quote: str) -> str | None:
        """Where the quote appears verbatim (ignoring case, spacing, and Unicode forms), or None."""
        paper = self.papers.get(paper_id)
        target = normalize(quote)
        if paper is None or len(target) < MIN_QUOTE_CHARS:
            return None
        if target in normalize(paper.abstract):
            return "abstract"
        rel = self.full_texts.get(paper_id)
        if rel is None:
            return None
        lines = (self.artifact_dir / rel).read_text(encoding="utf-8").splitlines()
        normalized = [normalize(line) for line in lines]
        joined, starts = "", []
        for text in normalized:
            starts.append(len(joined))
            joined += text + " "
        index = joined.find(target)
        if index < 0:
            return None
        line = max(i for i, start in enumerate(starts) if start <= index) + 1
        return f"{rel} line {line}"

    def save(self) -> None:
        data = {
            "services": self.literature.services if self.literature else [],
            "searches": self.searches,
            "papers": [p.as_dict() for p in self.papers.values()],
            "full_texts": self.full_texts,
            "figures": {k: [f.as_dict() for f in v] for k, v in self.figures.items()},
            "viewed": self.viewed,
        }
        (self.artifact_dir / LITERATURE_FILE).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                                      encoding="utf-8")  # fmt: skip


def _file_stem(arxiv_id: str) -> str:
    return arxiv_id.replace("/", "_")
