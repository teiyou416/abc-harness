"""OpenAlex works search (https://docs.openalex.org). No key needed."""

from __future__ import annotations

import json
from urllib.parse import urlencode

from abc_harness.literature.papers import Paper, arxiv_id_from, paper_id

API = "https://api.openalex.org/works"
FIELDS = "id,title,publication_year,doi,primary_location,locations,abstract_inverted_index,authorships"
# OpenAlex source IDs of the first-round venues (docs/project-spec.md, "Literature sources").
# FC proceedings are mostly listed under Lecture Notes in Computer Science, so this
# filter finds few FC papers; Semantic Scholar's venue filter covers FC when a key is set.
VENUE_SOURCES = {"FC": "S4306418423", "AFT": "S7407105243", "ICBC": "S4363608612"}


def search_url(query: str, limit: int, venues: list[str] | None) -> str:
    params = {"search": query, "per-page": str(limit), "select": FIELDS}
    if venues:
        params["filter"] = "primary_location.source.id:" + "|".join(VENUE_SOURCES[v] for v in venues)
    return f"{API}?{urlencode(params)}"


def parse(body: bytes, query: str) -> list[Paper]:
    papers = []
    for work in json.loads(body).get("results", []):
        doi = (work.get("doi") or "").removeprefix("https://doi.org/") or None
        arxiv = arxiv_id_from(doi) or next(
            (a for loc in work.get("locations") or [] if (a := arxiv_id_from(loc.get("landing_page_url")))), None
        )
        source = ((work.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
        openalex_id = str(work.get("id", "")).rsplit("/", 1)[-1]
        papers.append(Paper(
            id=paper_id(arxiv, doi, f"openalex:{openalex_id}"),
            title=work.get("title") or "(untitled)",
            year=work.get("publication_year"),
            venue=source,
            authors=[(a.get("author") or {}).get("display_name", "") for a in work.get("authorships") or []],
            abstract=_abstract(work.get("abstract_inverted_index")),
            url=f"https://doi.org/{doi}" if doi else str(work.get("id", "")),
            source="openalex",
            doi=doi,
            arxiv_id=arxiv,
            queries=[query],
        ))  # fmt: skip
    return papers


def _abstract(inverted: dict[str, list[int]] | None) -> str:
    """OpenAlex stores abstracts as word -> positions; rebuild the text."""
    if not inverted:
        return ""
    words: dict[int, str] = {}
    for word, positions in inverted.items():
        for position in positions:
            words[position] = word
    return " ".join(words[i] for i in sorted(words))
