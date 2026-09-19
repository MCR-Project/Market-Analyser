# tests — the fetcher test tree

This directory tests **`fetcher/` only**. The backend has its own suite at
`backend/tests/`; `pytest.ini` lists both as `testpaths`, so a bare `pytest` from
the repo root runs everything. The frontend's own (small) Vitest suite lives
beside the code it tests, under `app/src/`, and is run with `npm test` from
`app/` — it is not part of pytest.

`docker compose run --rm tests` (from the repo root) runs the same `pytest`
across both trees in a container built by `Dockerfile.tests` — for parity
with CI on a machine with no local Python/Node setup, not as a replacement
for running pytest directly. See the README's "Running it with Docker".

```
conftest.py            puts fetcher/ on sys.path
fetcher/test_*.py      one file per provider, plus test_common.py
fixtures/<provider>/   real captured payloads: HTML, JSON, CSV, XLSX
```

## Why `conftest.py` exists

Every module in `fetcher/` imports its shared helpers with a bare
`from common import ...` — the way it resolves when the module is run directly as
a script (`python fetcher/ark.py`), which is how these are actually used.
`fetcher/` has no `__init__.py` and is not a package, so importing those modules
under pytest needs `fetcher/` itself on `sys.path`, not just the repo root. That
is all `conftest.py` does.

## The rule

**No network access, ever.** Each provider module deliberately separates parsing
from fetching (`get_etf_list(payload)`, `parse_holdings_csv(bytes)`) precisely so
the parsers can be exercised against static fixtures. Tests call those; they never
call `fetch_etf_list` / `fetch_etf_holdings` and never construct a
`BrowserSession`.

`test_common.py` covers the shared runner (`run_fetcher`'s `--tickers`/`--limit`
filtering, per-fund error isolation, and skipping the delay after the last fund)
by passing it fake `fetch_etf_list` / `fetch_etf_holdings` callables and stubbing
`browser_session()` through an `autouse` fixture. `run_fetcher` accepts `argv`
explicitly for exactly this reason, so a test can drive the CLI without touching
real command-line args.

## Fixtures

`tests/fixtures/<provider>/` holds real captured responses, trimmed to a handful
of funds. Each provider has at least a fund-list fixture and a holdings fixture,
and most also have a **bond-fund** holdings fixture — the fixed-income case with
no ticker column, which every parser has to handle as an empty list plus a note
rather than a crash. Several have a degenerate case too (`fund_page_no_id.html`,
`holdings_empty.json`, `fund_finder_table_fallback.html`).

When adding a provider, capture the same set: the fund list, a normal equity
holdings file, a fixed-income holdings file, and whatever shape broke first while
you were writing the parser. Keep them small — the point is a parser assertion, not
an archive.

## Style

Plain `def test_*()` functions with `assert`, no classes. The only pytest fixture
in the tree is `test_common.py`'s `autouse` stub of `browser_session()`; the
provider tests need none, because they call parsers directly. Each file opens with
a short docstring naming the functions it covers and why they are testable in
isolation. Assertions state the *reason* where
it is not obvious — `# "arkk" appears twice in the fixture's nav - deduped, and
sorted.` is the register.
