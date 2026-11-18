# Gotchas

Traps someone already stepped on. This is the only append-only file in the
rulebook. Each entry is one line: a date, a title, the trap and the right move,
and the condition that retires it. The file holds 40 entries at most. Delete an
entry that no longer holds in the commit that makes it false. A gotcha that can
become a test should become one.

- **[2026-11-19] Papers With Code no longer serves papers** — the site from the architecture diagram now redirects to Hugging Face, so a retrieval tool built on it returns nothing. Use arXiv, DBLP, and Semantic Scholar as `docs/project-spec.md` lists. _Retire when: the architecture diagram no longer names Papers With Code._
- **[2026-11-19] SimBlock hard-codes its random seed** — `Main.java` creates `new Random(10)`, so repeated runs without a patch produce identical results. The SimBlock adapter writes the planned seed into each run's source copy. _Retire when: upstream SimBlock reads its seed from configuration._
- **[2026-11-19] SimBlock's Gradle wrapper does not run on current JDKs** — the pinned commit ships Gradle 6.7.1. Compile with `javac` and run `simblock.simulator.Main` with `src/dist/conf` on the classpath, as `SimBlock.command()` does. _Retire when: the pinned SimBlock commit ships a Gradle version that supports JDK 21._
- **[2026-11-19] `/sys/class/net` lists interfaces inside a `--network none` container** — kernel tunnel devices appear even without connectivity. Check that `/proc/net/route` holds only its header instead. _Retire when: never; this is how Linux reports devices._
