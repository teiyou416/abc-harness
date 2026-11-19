"""HTTP access for literature services, behind a small interface tests can replace.

`HttpFetcher` sends one GET request. `PoliteClient` adds what every service
asks of automated clients: a minimum pause between requests to the same host,
and a few retries on 429 and 5xx answers. Every wait fits inside the time the
caller still has, so a slow service cannot push a task past its limit.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlsplit

from abc_harness import __version__

USER_AGENT = f"abc-harness/{__version__} (research tool)"
# Minimum seconds between two requests to the same host.
MIN_INTERVAL = {"api.semanticscholar.org": 1.1, "api.openalex.org": 0.2, "arxiv.org": 3.0,
                "ar5iv.labs.arxiv.org": 3.0}  # fmt: skip
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_RETRIES = 2
REQUEST_TIMEOUT = 30.0


class FetchError(Exception):
    def __init__(self, url: str, status: int | None, detail: str) -> None:
        host = urlsplit(url).netloc
        super().__init__(f"{host} answered {status or 'nothing'}: {detail}")
        self.url, self.status = url, status


class Fetcher(Protocol):
    def get(self, url: str, headers: dict[str, str], timeout: float) -> bytes: ...


class HttpFetcher:
    def get(self, url: str, headers: dict[str, str], timeout: float) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            raise FetchError(url, e.code, e.reason or "error") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise FetchError(url, None, str(getattr(e, "reason", e))) from e


@dataclass
class PoliteClient:
    fetcher: Fetcher
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last: dict[str, float] = field(default_factory=dict)

    def get(self, url: str, time_left: float, headers: dict[str, str] | None = None) -> bytes:
        """GET `url`, waiting and retrying politely, within `time_left` seconds."""
        deadline = self.clock() + time_left
        host = urlsplit(url).netloc
        for attempt in range(MAX_RETRIES + 1):
            wait = self._last.get(host, -1e9) + MIN_INTERVAL.get(host, 1.0) - self.clock()
            if wait > 0:
                self._pause(wait, deadline, url)
            left = deadline - self.clock()
            if left <= 0:
                raise FetchError(url, None, "the task's active time ran out")
            self._last[host] = self.clock()
            try:
                return self.fetcher.get(url, headers or {}, min(REQUEST_TIMEOUT, left))
            except FetchError as e:
                if attempt == MAX_RETRIES or (e.status is not None and e.status not in RETRY_STATUS):
                    raise
                self._pause(2.0 * 2**attempt, deadline, url)
        raise AssertionError("unreachable")

    def _pause(self, seconds: float, deadline: float, url: str) -> None:
        if self.clock() + seconds >= deadline:
            raise FetchError(url, None, "waiting for the service would exceed the task's active time")
        self.sleep(seconds)
