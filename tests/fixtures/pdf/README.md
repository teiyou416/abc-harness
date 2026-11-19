# PDF fixtures

| File | Origin |
|---|---|
| `2007.05614/structured_content.json` | Recorded 2026-11-19: MinerU 4.2.3 (basic tier, CPU) output for the arXiv PDF of 2007.05614, **trimmed** to the first page (title, abstract, introduction) and the pages with Table 1 and Figures 1 and 2. The `extensions` block is removed. |
| `2007.05614/images/` | The cropped images of Table 1 and Figures 1 and 2 from the same parse. Equation crops are left out, as the harness deletes them. |
| `handwritten.pdf` | **Hand-written** one-page PDF (two headings, five sentences, standard Type 1 fonts). The Docker test parses it with the real parser image; the offline tests use it as the arXiv PDF. |

`FakeRunner.convert_pdf` copies `2007.05614/` whatever PDF it is given. To re-record, run
`mineru-kit parse <pdf> -o out.zip --format zip --tier basic` in the parser image and keep the same pages.
