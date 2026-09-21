# The daily job records its own runs; Freshness is not read off `last_fetch`

Freshness — whether the data being read comes from a recent run of the daily
fetch job or an old one — is answered from a record the job writes about itself:
one timestamp, taken when `fetch_daily.py` finishes. It is not derived from
`ticker.last_fetch`, the per-ticker column the job already stamps, and it is not
read off the dates of the prices themselves.

`last_fetch` cannot do this job. It is a *date*, taken from the runner's UTC clock,
and GitHub does not start the cron on time: across the 25 scheduled runs from 17
August to 19 September 2026 the start ranged from 15 minutes to 7 hours 41
minutes after the 22:30 UTC slot, and since 1 September every run has crossed
midnight UTC. Friday 18 September's run, which fetched Friday's close, started at
00:25 UTC on Saturday and stamped Saturday. So the same date can mean "Friday's run
started late" or "Thursday's run started very late", and a Friday run that never
happened is invisible until the next expected run also passes — Tuesday morning,
for a Friday miss. A timestamp of when a run finished has no such ambiguity, and
one record per run also covers the syncs `last_fetch` never sees (ETF holdings, the
risk-free rate) and a run that dies before it stamps anything.

The cost is a schema change and a new thing the job must remember to do: a
migration, a write in `fetch_daily.py` right after the price sync (before
compaction, which only tidies storage and changes nothing a reader sees), and tests
that a run which *finishes with failures* still leaves its record, with the count of
what failed. A run that crashes before it writes leaves no record at all, and so
does one whose own write fails: a record would claim a `finished_at` for a run that
did not finish, which is the false comfort this exists to remove. The missing record
is what makes the data read as behind. `last_fetch` keeps its own job — a null one
is what tells the next run to backfill that ticker — and is not repurposed.

## Considered options

- **Derive it from `ticker.last_fetch`** (the oldest active ticker's date) — no
  migration, and it exposes a partial failure. Rejected for the blind spot above:
  the date cannot say which day's run it came from, so a single missed run goes
  unnoticed for about a weekday. Inactive tickers would also have to be excluded,
  since their `last_fetch` never advances.
- **The latest price date in `prices`** — what the reader's data actually covers.
  Rejected: the question is whether the *job* ran, not what day the prices are
  from. The job runs on market holidays and adds no row, so a holiday would read as
  a miss and would need a market calendar to explain away.
