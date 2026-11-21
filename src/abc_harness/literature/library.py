"""The services a task may search (`Literature`) and the papers one task has found (`Library`).

The library is the only record of what the agent found. It is saved to
`literature.json` after every change, every full text goes to
`papers/<stem>.txt`, and every figure the agent views goes to
`papers/<stem>/figures/`. A quote counts only if `locate` finds it in a
found paper, and a figure reading only if the agent viewed that figure.

Full text comes from one of two tracks (`sources` records which): arXiv's
HTML rendering, or a PDF parsed by MinerU. A PDF is either one the researcher
supplied (`add_local`) or, when arXiv has no HTML for a paper, the arXiv PDF.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from abc_harness.literature import fulltext, openalex, pdf, semantic_scholar
from abc_harness.literature.figures import EXTENSIONS, Figure, media_type, slug
from abc_harness.literature.http import Fetcher, FetchError, PoliteClient
from abc_harness.literature.papers import Paper, normalize
from abc_harness.literature.pdf import PdfConvert, PdfError

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
    def __init__(
        self, artifact_dir: Path, literature: Literature | None = None, convert: PdfConvert | None = None
    ) -> None:
        self.artifact_dir = artifact_dir
        self.literature = literature
        self.convert = convert  # parses PDFs; None when the task has no PDF parser
        self.papers: dict[str, Paper] = {}
        self.searches: list[dict[str, Any]] = []
        self.full_texts: dict[str, str] = {}  # paper id -> path relative to the artifact directory
        self.figures: dict[str, list[Figure]] = {}  # paper id -> figures listed in its full text
        self.viewed: dict[str, dict[str, list[str]]] = {}  # paper id -> figure label -> saved image paths
        self.sources: dict[str, dict[str, Any]] = {}  # paper id -> where its full text came from and how
        # Local-library papers not parsed until first read: paper id -> the PDF, and how the agent saw it.
        self.shelf: dict[str, Path] = {}
        self.shelf_labels: dict[str, str] = {}

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
            library.sources = data.get("sources", {})
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
        """Fetch and save a paper's full text. Returns (path relative to the artifact directory, lines).

        arXiv HTML first; if arXiv has none and a PDF parser is available, the arXiv PDF parsed by MinerU.
        Raises FetchError or PdfError.
        """
        rel = self.full_texts.get(paper_id)
        if rel is None and paper_id in self.shelf:
            if self.convert is None:
                raise PdfError("this task has no PDF parser")
            label = self.shelf_labels[paper_id]
            rel = self._parse_local(paper_id, self.shelf[paper_id], f"PDF from the researcher's local library ({label})")
        elif rel is None:
            assert self.literature is not None
            paper = self.papers[paper_id]
            assert paper.arxiv_id
            stem = _file_stem(paper.arxiv_id)
            try:
                url, lines, figures = self.literature.full_text(paper.arxiv_id, time_left)
                header, source = [f"# Source: {url}"], {"kind": "arxiv_html", "url": url}
            except FetchError as html_error:
                if self.convert is None:
                    raise
                url = pdf.ARXIV_PDF_URL.format(id=paper.arxiv_id)
                data = self.literature.client.get(url, time_left)
                if not data.startswith(b"%PDF"):
                    raise FetchError(url, None, "the response is not a PDF") from html_error
                pdf_rel = f"{PAPERS_DIR}/{stem}.pdf"
                (self.artifact_dir / pdf_rel).parent.mkdir(exist_ok=True)
                (self.artifact_dir / pdf_rel).write_bytes(data)
                parsed, source = self._parse_pdf(pdf_rel, stem)
                source = {**source, "url": url, "html_error": str(html_error)}
                lines, figures, header = parsed.lines, parsed.figures, _pdf_header(f"{url} (no HTML on arXiv)", source)
            rel = self._save_text(paper_id, stem, header, lines, figures, source)
        return rel, (self.artifact_dir / rel).read_text(encoding="utf-8").splitlines()

    def add_local(self, path: Path) -> Paper:
        """Add a PDF the researcher supplied: copy it into the task, parse it, and make it citable. Raises PdfError."""
        if self.convert is None:
            raise PdfError("this task has no PDF parser")
        paper = self._register_local(path, path.name, "")
        self._parse_local(paper.id, path, f"PDF supplied by the researcher ({path.name})")
        return self.papers[paper.id]

    def shelve(self, path: Path, label: str, cached_output: Path | None = None) -> Paper:
        """List a PDF from the researcher's local library without parsing it; `read` parses it on first use.

        `label` is how the agent sees the file (e.g. papers/Some Title.pdf). With `cached_output`, an earlier
        parse of the same bytes, the entry shows the paper's own title and first abstract sentence.
        """
        title, abstract = path.stem, ""
        if cached_output is not None:
            try:
                data = json.loads((cached_output / pdf.OUTPUT_FILE).read_text(encoding="utf-8"))
                parsed = pdf.parse_structured(data, "")
                title, abstract = parsed.title or title, parsed.abstract
            except (OSError, ValueError, AttributeError, TypeError):
                pass  # the file name still identifies it
        paper = self._register_local(path, title, abstract)
        self.shelf[paper.id] = path
        self.shelf_labels[paper.id] = label
        self.save()
        return paper

    def _register_local(self, path: Path, title: str, abstract: str) -> Paper:
        name = slug(path.stem)[:40] or "paper"
        paper_id, n = f"local:{name}", 1
        while paper_id in self.papers:
            n += 1
            paper_id = f"local:{name}-{n}"
        stem = paper_id.replace(":", "-")
        paper = Paper(id=paper_id, title=title, year=None, venue="", authors=[], abstract=abstract,
                      url=f"{PAPERS_DIR}/{stem}.pdf", source="local")  # fmt: skip
        self.papers[paper_id] = paper
        return paper

    def _parse_local(self, paper_id: str, path: Path, origin: str) -> str:
        stem = paper_id.replace(":", "-")
        pdf_rel = f"{PAPERS_DIR}/{stem}.pdf"
        (self.artifact_dir / PAPERS_DIR).mkdir(exist_ok=True)
        (self.artifact_dir / pdf_rel).write_bytes(path.read_bytes())
        parsed, source = self._parse_pdf(pdf_rel, stem)
        source = {**source, "file": path.name}
        paper = self.papers[paper_id]
        paper.title = parsed.title or paper.title
        paper.abstract = parsed.abstract or paper.abstract
        return self._save_text(paper_id, stem, _pdf_header(origin, source), parsed.lines, parsed.figures, source)

    def _parse_pdf(self, pdf_rel: str, stem: str) -> tuple[pdf.ParsedPdf, dict[str, Any]]:
        assert self.convert is not None
        out_rel = f"{PAPERS_DIR}/{stem}/pdf"
        info = self.convert(self.artifact_dir / pdf_rel, self.artifact_dir / out_rel)
        try:
            data = json.loads((self.artifact_dir / out_rel / pdf.OUTPUT_FILE).read_text(encoding="utf-8"))
            parsed = pdf.parse_structured(data, out_rel)
        except (OSError, ValueError, AttributeError, TypeError) as e:
            raise PdfError(f"the PDF parser output could not be read: {e}") from e
        if not parsed.lines:
            raise PdfError("the PDF parser found no text in the PDF")
        source = {"kind": "pdf", "pdf": pdf_rel, "parser_output": out_rel, "parser_image_id": info.image_id,
                  "parser_revision": info.revision, "pdf_sha256": info.pdf_sha256,
                  "parse_seconds": round(info.seconds, 3), "cached": info.cached}  # fmt: skip
        return parsed, source

    def _save_text(self, paper_id: str, stem: str, header: list[str], lines: list[str], figures: list[Figure],
                   source: dict[str, Any]) -> str:  # fmt: skip
        rel = f"{PAPERS_DIR}/{stem}.txt"
        path = self.artifact_dir / rel
        path.parent.mkdir(exist_ok=True)
        path.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
        for figure in figures:
            figure.line += len(header)  # line numbers in the saved file, which starts with the header
        self.full_texts[paper_id] = rel
        self.figures[paper_id] = figures
        self.sources[paper_id] = source
        self.save()
        return rel

    def figure(self, paper_id: str, label: str) -> Figure | None:
        return next((f for f in self.figures.get(paper_id, []) if f.label.lower() == label.strip().lower()), None)

    def view(self, paper_id: str, label: str, time_left: float) -> tuple[Figure, list[tuple[str, bytes]], list[str]]:
        """Fetch and save a figure's images. Returns (figure, [(saved path, image bytes)], skipped notes).

        Formats the API refuses, such as SVG, are skipped with a note. A figure counts as viewed once at
        least one of its images could be shown.
        """
        figure = self.figure(paper_id, label)
        assert figure is not None
        folder = str(Path(self.full_texts[paper_id]).with_suffix("")) + "/figures"
        shown: list[tuple[str, bytes]] = []
        skipped: list[str] = []
        saved = self.viewed.get(paper_id, {}).get(figure.label)
        if saved:
            shown = [(rel, (self.artifact_dir / rel).read_bytes()) for rel in saved]
            return figure, shown, skipped
        for number, url in enumerate(figure.images, start=1):
            local = "://" not in url  # an image the PDF parser cropped, already saved in the task
            if local:
                data = (self.artifact_dir / url).read_bytes()
            else:
                assert self.literature is not None
                data = self.literature.client.get(url, time_left)
            kind = media_type(data)
            if kind is None:
                skipped.append(f"{url}: not an image format the model can view (for example SVG)")
                continue
            rel = url if local else f"{folder}/{slug(figure.label)}-{number}.{EXTENSIONS[kind]}"
            if not local:
                (self.artifact_dir / rel).parent.mkdir(parents=True, exist_ok=True)
                (self.artifact_dir / rel).write_bytes(data)
            shown.append((rel, data))
        if shown:
            self.viewed.setdefault(paper_id, {})[figure.label] = [rel for rel, _ in shown]
            self.save()
        return figure, shown, skipped

    def locate(self, paper_id: str, quote: str) -> str | None:
        """Where the quote appears verbatim (ignoring case, spacing, and Unicode forms), or None."""
        found = self._find(paper_id, quote)
        if found is None:
            return None
        rel, line = found
        return "abstract" if line == 0 else f"{rel} line {line}"

    def in_pdf_table(self, paper_id: str, quote: str) -> bool:
        """Whether the quote starts inside a table of a PDF-parsed full text, whose numbers may be wrong."""
        found = self._find(paper_id, quote)
        if found is None or found[1] == 0 or self.sources.get(paper_id, {}).get("kind") != "pdf":
            return False
        rel, line = found
        return pdf.is_table_line((self.artifact_dir / rel).read_text(encoding="utf-8").splitlines()[line - 1])

    def _find(self, paper_id: str, quote: str) -> tuple[str, int] | None:
        """(full text path, 1-based line) of the quote, ("abstract", 0) for the abstract, or None."""
        paper = self.papers.get(paper_id)
        target = normalize(quote)
        if paper is None or len(target) < MIN_QUOTE_CHARS:
            return None
        if target in normalize(paper.abstract):
            return "abstract", 0
        rel = self.full_texts.get(paper_id)
        if rel is None:
            return None
        lines = (self.artifact_dir / rel).read_text(encoding="utf-8").splitlines()
        # The header lines are the harness's own words, not the paper's.
        normalized = ["" if line.startswith(("# Source:", "# Note:")) else normalize(line) for line in lines]
        joined, starts = "", []
        for text in normalized:
            starts.append(len(joined))
            joined += text + " "
        index = joined.find(target)
        if index < 0:
            return None
        return rel, max(i for i, start in enumerate(starts) if start <= index) + 1

    def save(self) -> None:
        data = {
            "services": (self.literature.services if self.literature else []) + (["mineru_pdf"] if self.convert else []),
            "searches": self.searches,
            "papers": [p.as_dict() for p in self.papers.values()],
            "full_texts": self.full_texts,
            "figures": {k: [f.as_dict() for f in v] for k, v in self.figures.items()},
            "viewed": self.viewed,
            "sources": self.sources,
            "local_library": self.shelf_labels,
        }
        (self.artifact_dir / LITERATURE_FILE).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                                                      encoding="utf-8")  # fmt: skip


def _pdf_header(origin: str, source: dict[str, Any]) -> list[str]:
    cached = ", reused from the parse cache" if source["cached"] else ""
    return [(f"# Source: {origin}; parsed by {source['parser_revision']} in image "
            f"{source['parser_image_id']} ({source['parse_seconds']:.0f}s{cached})"), pdf.NOTE]  # fmt: skip


def _file_stem(arxiv_id: str) -> str:
    return arxiv_id.replace("/", "_")
