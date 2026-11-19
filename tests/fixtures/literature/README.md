# Literature fixtures

Responses that `tests/doubles/recorded_http.py` replays instead of calling the services.

| File | Origin |
|---|---|
| `openalex_venues_selfish_mining.json` | Recorded 2026-11-19 from OpenAlex: "selfish mining", 3 results, venues FC, AFT, ICBC. |
| `openalex_broad_propagation_delay.json` | Recorded 2026-11-19 from OpenAlex: "bitcoin block propagation delay", 3 results, no venue filter. |
| `arxiv_html_2007.05614.html` | Recorded 2026-11-19 from arxiv.org/html/2007.05614, **trimmed**: sections 4, 5, 7, and 8 removed to keep the repository small. Section 6 keeps Figures 1 to 3 and Table 1. |
| `arxiv_2007.05614v2_expected_horizon.png` | Recorded 2026-11-19: Figure 1 of that paper. |
| `handwritten_figure.svg` | **Hand-written** SVG that stands in for Figure 3, to test that formats the model cannot view are skipped. |
| `semantic_scholar_selfish_mining.json` | **Hand-written** from the documented response format of the Semantic Scholar paper search, because the API refused requests without a key. Replace it with a recorded response once a key is configured. |

To re-record, build each URL with the module's `search_url` function so it matches what the code requests.
