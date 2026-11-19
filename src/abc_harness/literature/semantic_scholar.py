"""Semantic Scholar paper search (https://api.semanticscholar.org). Practical only with an API key."""

from __future__ import annotations

import json
from urllib.parse import urlencode

from abc_harness.literature.papers import Paper, paper_id

API = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,year,venue,authors,abstract,externalIds,url"
# Venue names Semantic Scholar uses for the first-round venues. Not verified
# against the live API yet; check them once a key is configured.
VENUE_NAMES = {
    "FC": ["Financial Cryptography", "Financial Cryptography and Data Security"],
    "AFT": ["ACM Conference on Advances in Financial Technologies", "AFT"],
    "ICBC": ["IEEE International Conference on Blockchain and Cryptocurrency", "ICBC"],
}


def search_url(query: str, limit: int, venues: list[str] | None) -> str:
    params = {"query": query, "limit": str(limit), "fields": FIELDS}
    if venues:
        params["venue"] = ",".join(name for v in venues for name in VENUE_NAMES[v])
    return f"{API}?{urlencode(params)}"


def parse(body: bytes, query: str) -> list[Paper]:
    papers = []
    for item in json.loads(body).get("data") or []:
        ids = item.get("externalIds") or {}
        doi = ids.get("DOI")
        arxiv = ids.get("ArXiv")
        papers.append(Paper(
            id=paper_id(arxiv, doi, f"s2:{item.get('paperId')}"),
            title=item.get("title") or "(untitled)",
            year=item.get("year"),
            venue=item.get("venue") or "",
            authors=[a.get("name", "") for a in item.get("authors") or []],
            abstract=item.get("abstract") or "",
            url=item.get("url") or "",
            source="semantic_scholar",
            doi=doi,
            arxiv_id=arxiv,
            queries=[query],
        ))  # fmt: skip
    return papers
