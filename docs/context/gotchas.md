# Gotchas

Traps someone already stepped on. This is the only append-only file in the
rulebook. Each entry is one line: a date, a title, the trap and the right move,
and the condition that retires it. The file holds 40 entries at most. Delete an
entry that no longer holds in the commit that makes it false. A gotcha that can
become a test should become one.

- **[2026-11-19] SimBlock hard-codes its random seed** — `Main.java` creates `new Random(10)`, so repeated runs without a patch produce identical results. The SimBlock adapter writes the planned seed into each run's source copy. _Retire when: upstream SimBlock reads its seed from configuration._
- **[2026-11-19] SimBlock's Gradle wrapper does not run on current JDKs** — the pinned commit ships Gradle 6.7.1. Compile with `javac` and run `simblock.simulator.Main` with `src/dist/conf` on the classpath, as `SimBlock.command()` does. _Retire when: the pinned SimBlock commit ships a Gradle version that supports JDK 21._
- **[2026-11-19] `/sys/class/net` lists interfaces inside a `--network none` container** — kernel tunnel devices appear even without connectivity. Check that `/proc/net/route` holds only its header instead. _Retire when: never; this is how Linux reports devices._
- **[2026-11-19] BlockSim never seeds its random generators** — `random` and `numpy.random` run unseeded, so two runs with the same configuration differ. The BlockSim adapter seeds both in `Main.py`. _Retire when: upstream BlockSim takes a seed._
- **[2026-11-19] BlockSim's Runs > 1 keeps only the last run** — `Main.py` clears its statistics after each run and rewrites the same Excel file. The adapter forces `Runs = 1` and repeats with seeds instead. _Retire when: upstream writes one result per run._
- **[2026-11-19] BlockSim needs pandas below 2** — it calls `ExcelWriter.save()`, which pandas 2 removed. The image pins pandas 1.5.3. _Retire when: upstream calls `close()`._
- **[2026-11-19] DBLP answers scripts with a bot check** — every dblp.org mirror returns HTTP 202 with a "Making sure you're not a bot!" page instead of search results, so a DBLP search tool finds nothing. The literature layer uses OpenAlex and Semantic Scholar instead. _Retire when: the DBLP search API answers an automated request with JSON again._
- **[2026-11-19] Semantic Scholar refuses requests without a key** — the shared unauthenticated pool answers 429 on the first request. Set `SEMANTIC_SCHOLAR_API_KEY` in `.env`; without it the harness searches OpenAlex only. _Retire when: unauthenticated requests succeed reliably, or a key is always configured._
- **[2026-11-19] arXiv's search API answered 429 to every request** — `export.arxiv.org/api/query` refused even single requests a minute apart, while arxiv.org/html pages loaded. The harness uses arXiv only for full text and finds arXiv papers through OpenAlex and Semantic Scholar. _Retire when: the arXiv API answers normal request rates and a search tool needs it._
- **[2026-11-19] FC papers in OpenAlex sit under Lecture Notes in Computer Science** — OpenAlex's source "Financial Cryptography" holds only 21 works, so the venue filter misses most FC papers. Semantic Scholar's venue filter covers FC when a key is set. _Retire when: OpenAlex lists FC proceedings under their own source._
