# Gotchas

Traps someone already stepped on. This is the only append-only file in the
rulebook. Each entry is one line: a date, a title, the trap and the right move,
and the condition that retires it. The file holds 40 entries at most. Delete an
entry that no longer holds in the commit that makes it false. A gotcha that can
become a test should become one.

- **[2026-11-19] Papers With Code no longer serves papers** — the site from the architecture diagram now redirects to Hugging Face, so a retrieval tool built on it returns nothing. Use arXiv, DBLP, and Semantic Scholar as `docs/project-spec.md` lists. _Retire when: the architecture diagram no longer names Papers With Code._
