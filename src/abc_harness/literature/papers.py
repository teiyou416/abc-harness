"""One paper record, shared by every source, and the quote check for citations."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

ARXIV_ID = re.compile(r"(\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?", re.IGNORECASE)


@dataclass
class Paper:
    """A paper as the agent sees it. `id` is stable across sources: arxiv:, doi:, or the source's own ID."""

    id: str
    title: str
    year: int | None
    venue: str
    authors: list[str]
    abstract: str
    url: str
    source: str
    doi: str | None = None
    arxiv_id: str | None = None
    queries: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def brief(self) -> str:
        """The text the model sees in a search result."""
        authors = ", ".join(self.authors[:3]) + (" et al." if len(self.authors) > 3 else "")
        lines = [
            f"### {self.id}",
            f"{self.title} ({self.year or 'n.d.'}). {authors}. {self.venue or 'venue unknown'}.",
            f"Full text: {self.full_text_note()}.",
            f"Abstract: {self.abstract or '(no abstract available)'}",
        ]
        return "\n".join(lines)

    def full_text_note(self) -> str:
        if self.source == "local":
            return "a PDF the researcher supplied; read_paper opens it"
        return "read_paper can fetch it" if self.arxiv_id else "not available (no arXiv version)"


def paper_id(arxiv_id: str | None, doi: str | None, fallback: str) -> str:
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    if doi:
        return f"doi:{doi.lower()}"
    return fallback


def arxiv_id_from(text: str | None) -> str | None:
    """Extract a versionless arXiv ID from an arXiv URL or a 10.48550/arXiv DOI."""
    if not text:
        return None
    lowered = text.lower()
    if "arxiv" not in lowered:
        return None
    tail = re.split(r"arxiv[./:]|/abs/|/pdf/", text, flags=re.IGNORECASE)[-1]
    match = ARXIV_ID.search(tail)
    return match.group(1) if match else None


def normalize(text: str) -> str:
    """Fold the differences a faithful quote may have from the source: Unicode forms, case, spacing, quotes."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-").replace("­", "")
    return re.sub(r"\s+", " ", text).strip().lower()
