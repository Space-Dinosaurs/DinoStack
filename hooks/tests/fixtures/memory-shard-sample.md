# Memory

## How this file is managed

This is a synthetic fixture for the memory-shard compiler's test suite
(DS-221 Unit 1) - it is NOT this repo's own root MEMORY.md, which is
untracked by design and must never be read or written by these tests.

## Facts

- **2026-01-05: First entry, an ordinary single-line fact.** Nothing
  special about this one - baseline case.
- **2026-01-06: Second entry, immediately adjacent to the first.** Also a
  single physical line.
- **2026-01-02: Third entry - a deliberate DATE INVERSION.** This entry's
  own date (2026-01-02) sorts earlier than the two entries above it
  (2026-01-05, 2026-01-06), mirroring the corpus's real documented
  inversions. Sort order in the compiled file must follow `sequence`, not
  this date string.
- **2026-01-07: Fourth entry, with a code fence in its body.**
  ```bash
  echo "hello from inside an entry" && exit 0
  ```
  The fence's own blank-looking indentation must round-trip byte-for-byte.
- **2026-01-08: Fifth entry, has MULTIPLE trailing blank lines after it.**
  This entry is deliberately followed by three blank lines before the next
  entry begins, to exercise the "shard body captures its own trailing
  whitespace verbatim" rule.



- **2026-01-09: Sixth entry, immediately after the multi-blank-line gap.**
  Ordinary single-line entry again.
- **2026-01-10: Seventh entry.** Plain.
- **2026-01-11: Eighth entry, a two-line continuation.**
  This second physical line is a continuation of the same entry, not a
  separate one - it does not start with "- ".
- **2026-01-12: Ninth entry.** Plain.
- **2026-01-13: Tenth entry, references DS-221 explicitly for slug testing.**
  Mentions DS-221 so the mechanical slug derivation picks it up.
- **2026-01-14: Eleventh entry.** Plain.
- **2026-01-15: Twelfth entry.** Plain.
- **2026-01-16: Thirteenth entry.** Plain.
- **2026-01-17: Fourteenth entry, no trailing blank line before EOF-adjacent entry.**
  Plain continuation line.
- **2026-01-18: Fifteenth entry, the final entry in the fixture.** Ends the
  file with a single trailing newline, no extra blank lines.
