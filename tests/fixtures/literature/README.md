# Literature fixtures

Responses that `tests/doubles/recorded_http.py` replays instead of calling the services.

| File | Origin |
|---|---|
| `openalex_venues_selfish_mining.json` | Recorded 2026-11-19 from OpenAlex: "selfish mining", 3 results, venues FC, AFT, ICBC. |
| `openalex_broad_propagation_delay.json` | Recorded 2026-11-19 from OpenAlex: "bitcoin block propagation delay", 3 results, no venue filter. |
| `arxiv_html_2007.05614.html` | Recorded 2026-11-19 from arxiv.org/html/2007.05614, **trimmed** before section 4 to keep the repository small. |
| `semantic_scholar_selfish_mining.json` | **Hand-written** from the documented response format of the Semantic Scholar paper search, because the API refused requests without a key. Replace it with a recorded response once a key is configured. |

To re-record, build each URL with the module's `search_url` function so it matches what the code requests.
