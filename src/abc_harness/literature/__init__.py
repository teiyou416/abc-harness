"""Literature search and reading for the agent (milestone M4).

The harness, not the model, talks to the academic services. Every paper a
search returns enters the task's `Library`, which saves it to
`literature.json`. A plan may cite only papers in that library, with a quote
the harness finds verbatim in the paper's abstract or saved full text, or with
a figure reading from a figure the agent viewed.
"""

from abc_harness.literature.http import Fetcher, FetchError, HttpFetcher
from abc_harness.literature.library import Library, Literature
from abc_harness.literature.papers import Paper

__all__ = ["FetchError", "Fetcher", "HttpFetcher", "Library", "Literature", "Paper"]
