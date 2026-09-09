# fetcher — provider holdings scrapers

One module per ETF provider, each scraping that provider's public website for the
**full** constituent list of every fund it offers, and writing a shared JSON
schema. This exists because yfinance only exposes an ETF's top ~10 holdings; the
whole tracked universe below that line comes from here.

```
common.py     the shared contract: schema, CLI runner, BrowserSession
vaneck.py  spdr.py  ark.py  ishares.py  vanguard.py  invesco.py
```

Nothing in `backend/` imports this package, and nothing here imports `backend/`.
The only interface between them is the JSON file:
`backend/scripts/complete_database.py --holdings-json <path>`.

## Running one

From the **repo root**, with `fetcher/requirements.txt` installed plus a one-time
`playwright install chromium`:

```bash
python fetcher/vaneck.py --output vaneck_holdings.json
python fetcher/vaneck.py --limit 5            # quick test on five funds
python fetcher/spdr.py --tickers SPY MDY      # only these funds
```

Flags come from `run_fetcher` and are identical everywhere: `--output`,
`--delay` (default 1.5s between holdings requests), `--limit`, `--tickers`.
No API keys are required for any provider.

Both stages also run end-to-end through the "Fetch holdings and complete
database (manual)" GitHub Action, which picks the provider from a dropdown and
uploads the raw JSON as an artifact *before* touching Supabase, so the scrape
survives a failed completion step.

## The output schema

Defined and written by `common.write_output`; documented at the top of
`common.py`. Any new fetcher only has to build `EtfResult` objects and call it.

```json
{
  "generated_at": "2026-07-14T09:09:39",
  "etfs": [{
    "ticker": "SMH",
    "name": "VanEck Semiconductor ETF",
    "note": null,       // e.g. "non-equity fund, no stock tickers"
    "error": null,      // set when this one fund failed
    "holdings": [{"ticker": "NVDA", "name": "Nvidia Corp", "weight_pct": 19.86}]
  }]
}
```

`note` and `error` are different states and the consumer treats them
differently: a fixed-income fund with no ticker column is a `note` and a legit
empty holdings list, while a fetch or parse failure is an `error`. Both are
skipped by `complete_database.py`, but only one of them means something broke.

## `common.py`

**`run_fetcher(provider_name, fetch_etf_list, fetch_etf_holdings, default_output, tickers_example)`**
is the entire CLI and orchestration: argument parsing, `--tickers`/`--limit`
filtering, the numbered progress loop with per-fund error isolation, the pacing
delay, `write_output`, and the summary. A fetcher differs only in its name, its
two functions and its default filename — everything else lives here once instead
of six times (issue #23). If `fetch_etf_list` accepts a `delay` parameter it is
passed one (only `ark.py` needs it, because building its list costs one request
per fund).

**`BrowserSession`** is a Playwright-backed stand-in for `requests.Session`, and
every provider goes through it — not just the ones that need a browser. Two ways
to reach a provider:

- `.get(url, params=...)` — a raw HTTP request through the browser context: real
  TLS/HTTP fingerprint and shared cookies, but no page render and no JS. This is
  the default, lightweight path and is enough for five of the six providers.
- `.open_page(url)` then `.fetch_json(url, params=...)` — loads a real page once
  so the site's own JS can resolve whatever bot check is in place, then issues
  `fetch()` calls from **inside that page's JS engine** for as many URLs as
  needed, with no per-fund reload.

Only `invesco.py` needs the second path, and the reason is worth keeping:
`www.invesco.com` answers plain HTTP clients with 406 at the domain level —
verified with a full browser header set, and with `BrowserSession.get()` itself.
A real page load gets past it; a decoupled HTTP client reusing that page's
cookies does not.

`Response` adapts a Playwright `APIResponse` to the `requests.Response` surface
(`.status_code`, `.headers` lowercased, `.content`, `.text`, `.json()`,
`.raise_for_status()`) so parsing code did not have to be rewritten when the
package moved off `requests`. `.text` always decodes UTF-8 with replacement,
rather than trusting each provider's `Content-Type`.

## Adding a provider

1. Create `fetcher/<provider>.py`. Import from `common` with a **bare**
   `from common import ...` — these modules are run as scripts, not as a package
   (`fetcher/` has no `__init__.py`).
2. Write a module docstring in the style of the existing ones: what it retrieves,
   the exact endpoints **and how they were verified**, the usage examples, and
   any provider quirk (a header row buried under title rows, a fund type with no
   ticker column, a bot check). These docstrings are the record of hours of
   manual network inspection — they are the most valuable thing in the file.
3. Split parsing from fetching. `get_etf_list(payload_or_html)` and
   `parse_holdings_*(bytes)` take already-fetched content precisely so they can
   be unit-tested against static fixtures with no network; `fetch_etf_list` /
   `fetch_etf_holdings` are the thin request wrappers around them.
4. Raise a `RuntimeError` naming the likely cause when a list comes back empty
   ("The API has probably changed"). A silent empty list is how a provider
   redesign gets discovered three weeks later.
5. `main()` is one call to `run_fetcher`.
6. Add fixtures and tests under `tests/fetcher/` and `tests/fixtures/<provider>/`.
7. Add the provider to the `provider` choice list in
   `.github/workflows/fetch-holdings.yml`.

## The country-collision hazard

**This is the trap this package exists to avoid, and every international fund
hits it.** Providers reuse plain ticker symbols across countries with no exchange
suffix: `ROP` is both Roper Technologies (US, NASDAQ) and Roche's Swiss listing,
in the same file. Trusting the bare ticker inserts one company's price history
under another company's identity, downstream, after yfinance has happily
validated it.

Each provider needs its own filter, and the three found so far are all different:

| Provider | Filter |
| --- | --- |
| iShares | `Location == "United States"` and `Asset Class == "Equity"` |
| Vanguard | `isin` starts with `US` (ISO 3166-1 country code) |
| Invesco | `localCurrencyName == "US Dollar"` and `securityTypeName == "Common Stock"` |

Note the Invesco detail: its `currency` field is always `"USD"` — the fund's
reporting currency, not the security's — so only `localCurrencyName` is accurate.
A new international provider needs this question answered **before** its output
reaches `complete_database.py`, and the answer belongs in the module docstring.

Fixed-income funds are the other recurring shape: their holdings files have no
ticker column at all. Detect it and return an empty list with a `note`, never a
crash.

## Testing

`tests/fetcher/`, fixture-driven, no network. See `tests/CLAUDE.md`.
