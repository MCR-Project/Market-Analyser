"""The shape of `.github/workflows/fetch-holdings.yml` (issue #169).

The workflow cannot be executed in CI, and its cron cannot be fired on demand, so
what can be pinned down is the structure the issue's acceptance criteria are
really claims about: it fires on Sundays only, scrapes the six providers as
independent parallel jobs, and completes the database in exactly one job that
runs whatever the scrapes did. Each assertion states the failure it prevents.

PyYAML reads the bare key `on` as the boolean True, hence `workflow[True]`.
"""
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = REPO_ROOT / ".github" / "workflows"


def _load(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def _steps(job: dict) -> list[dict]:
    return job["steps"]


def _step_runs(job: dict) -> str:
    return "\n".join(s.get("run", "") for s in _steps(job))


def _day_of_week(cron: str) -> str:
    return cron.split()[4]


def _days(field: str) -> set[int]:
    """Expand a cron day-of-week field ("0", "1-5", "1,3", "*") into the set of
    days it names, so the overlap test survives the daily cron being rewritten."""
    if field == "*":
        return set(range(7))
    days: set[int] = set()
    for part in field.split(","):
        first, _, last = part.partition("-")
        days |= set(range(int(first), int(last or first) + 1))
    return days


def _fetcher_providers() -> set[str]:
    # Everything in fetcher/ that is a provider module; common.py is the shared contract.
    return {p.stem for p in (REPO_ROOT / "fetcher").glob("*.py") if p.stem != "common"}


def test_schedule_fires_on_sundays_only():
    # The daily job owns Monday-Friday; a weekly run on any of those days would
    # overlap it, and two writers on the same tables is what the split avoids.
    crons = _load("fetch-holdings.yml")[True]["schedule"]
    assert len(crons) == 1
    assert _day_of_week(crons[0]["cron"]) == "0"


def test_schedule_never_shares_a_day_with_the_daily_job():
    weekly = _day_of_week(_load("fetch-holdings.yml")[True]["schedule"][0]["cron"])
    daily = _day_of_week(_load("fetch-daily.yml")[True]["schedule"][0]["cron"])
    assert not _days(weekly) & _days(daily)


def test_manual_dispatch_keeps_provider_dry_run_and_limit():
    # A single-provider dry run with a limit is how a scraper change gets
    # checked without touching Supabase; dropping any one input loses that.
    inputs = _load("fetch-holdings.yml")[True]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"provider", "dry_run", "limit"}


def test_dispatch_can_pick_every_provider_or_all_of_them():
    options = _load("fetch-holdings.yml")[True]["workflow_dispatch"]["inputs"]["provider"]["options"]
    assert "all" in options
    assert set(options) - {"all"} == _fetcher_providers()


def test_matrix_covers_exactly_the_fetcher_modules():
    # The matrix is the one list of providers a scheduled run uses. A provider
    # added to fetcher/ and not here would silently never be scraped weekly.
    matrix = _load("fetch-holdings.yml")["jobs"]["scrape"]["strategy"]["matrix"]["provider"]
    literal = re.search(r"'(\[[^\]]*\])'", matrix).group(1)
    assert set(re.findall(r'"(\w+)"', literal)) == _fetcher_providers()


def test_a_failed_provider_does_not_cancel_the_others():
    strategy = _load("fetch-holdings.yml")["jobs"]["scrape"]["strategy"]
    assert strategy["fail-fast"] is False


def test_scrape_jobs_never_touch_supabase():
    # Scraping runs six at a time; only the completion job holds credentials.
    scrape = _load("fetch-holdings.yml")["jobs"]["scrape"]
    assert "SUPABASE" not in yaml.safe_dump(scrape)
    assert "complete_database" not in _step_runs(scrape)


def test_a_scrape_uploads_its_json_only_when_it_succeeded():
    # A failed provider must leave no artifact, so completion cannot read a
    # half-written file and its funds' rows stay untouched.
    upload = [s for s in _steps(_load("fetch-holdings.yml")["jobs"]["scrape"])
              if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    assert len(upload) == 1
    assert "if" not in upload[0]
    assert upload[0]["with"]["name"] == "holdings-${{ matrix.provider }}"


def test_exactly_one_job_runs_complete_database():
    jobs = _load("fetch-holdings.yml")["jobs"]
    completing = [name for name, job in jobs.items() if "complete_database.py" in _step_runs(job)]
    assert len(completing) == 1


def test_completion_waits_for_every_scrape_but_runs_even_if_some_failed():
    # `needs` alone would skip completion when any scrape failed, which is
    # exactly when the other five providers' funds still need completing.
    jobs = _load("fetch-holdings.yml")["jobs"]
    (name,) = [n for n, j in jobs.items() if "complete_database.py" in _step_runs(j)]
    job = jobs[name]
    assert job["needs"] == "scrape" or job["needs"] == ["scrape"]
    assert job["if"].replace(" ", "") in {"${{!cancelled()}}", "${{always()}}"}


def test_completion_honours_dry_run():
    jobs = _load("fetch-holdings.yml")["jobs"]
    runs = "\n".join(_step_runs(j) for j in jobs.values() if "complete_database.py" in _step_runs(j))
    assert "inputs.dry_run" in runs
    assert "--dry-run" in runs


def test_two_runs_never_complete_at_once():
    # Completion computes the DB-wide tracked/untracked split, so a scheduled run
    # overlapping a manual one would race exactly as parallel completions would.
    concurrency = _load("fetch-holdings.yml")["concurrency"]
    assert concurrency["cancel-in-progress"] is False


def _metadata_job() -> dict:
    jobs = _load("fetch-holdings.yml")["jobs"]
    (name,) = [n for n, j in jobs.items() if "sync_untracked_metadata.py" in _step_runs(j)]
    return jobs[name]


def test_untracked_metadata_runs_after_completion_even_if_it_failed():
    # Completion decides which stocks are Untracked and copies a demoted stock's
    # own metadata across, so the lookup follows it. It must not be skipped when
    # a scrape or the completion went red: it reads the flags as they stand, and
    # `needs` alone would skip it exactly then (issue #170).
    job = _metadata_job()
    jobs = _load("fetch-holdings.yml")["jobs"]
    (completing,) = [n for n, j in jobs.items() if "complete_database.py" in _step_runs(j)]
    assert job["needs"] == completing or job["needs"] == [completing]
    assert job["if"].replace(" ", "") in {"${{!cancelled()}}", "${{always()}}"}


def test_untracked_metadata_honours_dry_run():
    runs = _step_runs(_metadata_job())
    assert "inputs.dry_run" in runs
    assert "--dry-run" in runs


def test_untracked_metadata_is_not_gated_on_a_scrape_having_produced_a_file():
    # Unlike the completion's steps it has nothing to do with this week's files.
    assert all("steps.files" not in str(s.get("if", "")) for s in _steps(_metadata_job()))
