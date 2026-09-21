-- Record each run of the daily fetch job, for the header's Freshness (issue #154,
-- docs/adr/0003-the-daily-job-records-its-own-runs.md).
--
-- The header has to say whether the data being read comes from a recent run of
-- scripts/fetch_daily.py or an old one, and nothing the pipeline already writes
-- can answer that. ticker.last_fetch is the closest, and is not close enough: it
-- is a *date* taken from the runner's UTC clock, and GitHub does not start the
-- scheduled workflow on time - across the 25 runs from 17 August to 19 September
-- 2026 the start ranged from 15 minutes to 7h 41m late, and every run since
-- 1 September has started after midnight UTC. A Friday run that started at 00:25
-- on Saturday stamps Saturday; a Thursday run started late stamps Friday. The
-- same date means either, so a Friday run that never happens goes unnoticed until
-- the Tuesday after. last_fetch also keeps its own job (a null one tells the next
-- run to backfill that ticker) and is not repurposed.
--
-- One row per run, written by fetch_daily.py right after its price sync and
-- before compaction. finished_at is the column's own default, so it is the
-- database's clock at the moment of the write, not the runner's. `failed` is the
-- number of distinct ids the run could not refresh (ETF sync, the risk-free rate,
-- prices, metadata); compaction failures are not counted, because they leave the
-- data exactly as fresh as it was. A run that crashes, or whose own write fails,
-- leaves no row at all - a row would claim a finish time for a run that did not
-- finish - and the missing row is what makes the data read as behind.
--
-- The table gains about 250 rows a year and is only ever read as
-- `order by finished_at desc limit 1`, so it needs no pagination and no
-- compaction. RLS is enabled with no policies, like every other table here: only
-- the backend's service key can read or write it.
--
-- Applied via Supabase's apply_migration; kept here for review/history. Apply it
-- BEFORE the first run of the job that writes to it, or that run goes red on the
-- insert (and the header reads unknown until a run has written a row).

create table if not exists fetch_run (
    id bigint generated always as identity primary key,
    finished_at timestamptz not null default now(),
    failed integer not null default 0 check (failed >= 0)
);
alter table fetch_run enable row level security;

create index if not exists fetch_run_finished_at_idx on fetch_run (finished_at desc);
