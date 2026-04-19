# Session transcript

Authoritative record of the session just completed.

## Summary

Branch: `fix/ord-612-timezone`
Ticket: ORD-612.
Task: fix the timezone-rounding bug that caused same-day orders to land
under the wrong `calendar_date` bucket near midnight UTC boundaries.
Engineer completed fix pass 1 and Skeptic reviewed the diff.

## What happened

1. Engineer pass 1 edited `src/handlers/orders.ts` to compute
   `calendar_date` via the shop's IANA timezone rather than server UTC.
   Committed as `fix(orders): localize calendar bucketing` sha `71c9e42`.
2. Skeptic reviewed the diff and raised one Major finding: the fix uses
   JS `toLocaleDateString()` with a hardcoded `"en-US"` locale argument,
   which returns `M/D/YYYY` ordering. Downstream reports parse the
   string as `D/M/YYYY` via the reporting library default. This
   swapped-ordering bug has been observed twice before:
   - Instance A: `src/reports/daily.ts:84` (commit `5ad2110`, last
     quarter) - report generation used `toLocaleDateString` without
     locale and week-of-month rollups were wrong for two weeks.
   - Instance B: `src/exports/csv.ts:112` (commit `92ab440`, two months
     ago) - CSV export wrote dates in the en-US format that the partner
     ingestion job parsed as en-GB. Dropped 11K rows.
   This is the third instance of "implicit locale in date formatting
   leads to cross-system parsing mismatch".
3. Engineer acknowledged. Skeptic has NOT yet promoted this finding to
   `.agentic/findings.md`; promotion is pending /wrap.
4. Follow-up ticket ORD-620 was opened to switch to explicit ISO-8601
   (`YYYY-MM-DD`) strings across all cross-system date outputs. Not
   attempted this session.

## State at wrap time

- Current branch: `fix/ord-612-timezone`.
- `git status --porcelain`: clean.
- Stashes: none.
- Open PR: #572 (draft). Marked ready after ORD-620 lands.
- Next steps: implement ORD-620 (switch to ISO-8601 date strings across
  reports, CSV export, and the orders handler); land it; mark #572
  ready.

## Stable architectural facts established this session

None beyond the pattern captured in the Skeptic finding above.

## Skeptic findings

- One new Major finding this session: implicit-locale date formatting
  produces cross-system parsing mismatches. Two prior instances cited.
  Not yet promoted.

## Tools used

Read, Edit, Grep, Bash (jest, git).

## Specialist agents

None ran this session.
