"""RecordedFetcher replays recorded HTTP responses for literature tests (see tests/fixtures/literature/).

A request for a URL without a recorded response fails with 404, so a test also
catches a request the code was not expected to make. `failures` makes chosen
URLs fail with given statuses first, to exercise retries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from abc_harness.literature import Literature, openalex, semantic_scholar
from abc_harness.literature.http import FetchError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "literature"
VENUES = ["FC", "AFT", "ICBC"]
RECORDED = {
    openalex.search_url("selfish mining", 3, VENUES): "openalex_venues_selfish_mining.json",
    openalex.search_url("bitcoin block propagation delay", 3, None): "openalex_broad_propagation_delay.json",
    semantic_scholar.search_url("selfish mining", 3, VENUES): "semantic_scholar_selfish_mining.json",
    "https://arxiv.org/html/2007.05614": "arxiv_html_2007.05614.html",
}


@dataclass
class RecordedFetcher:
    failures: dict[str, list[int]] = field(default_factory=dict)
    requests: list[tuple[str, dict[str, str]]] = field(default_factory=list)

    def get(self, url: str, headers: dict[str, str], timeout: float) -> bytes:
        self.requests.append((url, dict(headers)))
        if self.failures.get(url):
            raise FetchError(url, self.failures[url].pop(0), "recorded failure")
        if url not in RECORDED:
            raise FetchError(url, 404, "no recorded response")
        return (FIXTURES / RECORDED[url]).read_bytes()


class FakeTime:
    """A clock that only moves when the code sleeps, so politeness waits cost no real time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def recorded_literature(s2_key: str | None = None, **failures: list[int]) -> tuple[Literature, RecordedFetcher]:
    fetcher = RecordedFetcher(failures=dict(failures))
    time = FakeTime()
    return Literature(fetcher, s2_key, clock=time.clock, sleep=time.sleep), fetcher
