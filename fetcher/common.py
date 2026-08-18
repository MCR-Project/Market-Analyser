"""
Shared contract for provider holdings fetchers.

Every fetcher in this folder (vaneck.py, ...) scrapes one ETF provider's
public website and writes a JSON file with this exact schema:

    {
      "generated_at": "2026-07-14T09:09:39",
      "etfs": [
        {
          "ticker": "SMH",
          "name": "VanEck Semiconductor ETF",
          "note": null,       # e.g. "non-equity fund, no stock tickers"
          "error": null,      # set when fetching/parsing this fund failed
          "holdings": [
            {"ticker": "NVDA", "name": "Nvidia Corp", "weight_pct": 19.86},
            ...
          ]
        },
        ...
      ]
    }

That file is what backend/scripts/complete_database.py --holdings-json
consumes to complete the Supabase universe, so any new fetcher only has to
build EtfResult objects and call write_output() to be compatible.

Every fetcher talks to its provider through BrowserSession below, a thin
Playwright-backed stand-in for requests.Session - real browser TLS/HTTP
fingerprint and cookie handling, which matters for providers that gate
plain HTTP clients (see fetcher/invesco.py), and headroom for
per-provider bot-check handling without rewriting each fetcher's own
parsing logic.
"""

import argparse
import inspect
import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple, Union
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

# Provider sites tend to reject requests without a browser-like User-Agent.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


@dataclass
class EtfHolding:
    ticker: str
    name: str
    weight_pct: Optional[float]


@dataclass
class EtfFund:
    ticker: str
    name: str
    product_url: str
    holdings_url: str


@dataclass
class EtfResult:
    etf_ticker: str
    etf_name: str
    holdings: List[EtfHolding] = field(default_factory=list)
    note: Optional[str] = None    # e.g. "non-equity fund, no stock tickers"
    error: Optional[str] = None


def write_output(results: List[EtfResult], path: str) -> None:
    """Write the fetcher results as the JSON schema documented above."""
    output = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "etfs": [
            {
                "ticker": r.etf_ticker,
                "name": r.etf_name,
                "note": r.note,
                "error": r.error,
                "holdings": [
                    {"ticker": h.ticker, "name": h.name, "weight_pct": h.weight_pct}
                    for h in r.holdings
                ],
            }
            for r in results
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)


def run_fetcher(
    provider_name: str,
    fetch_etf_list: Callable[..., List[EtfFund]],
    fetch_etf_holdings: Callable[[BrowserSession, str], Tuple[List[EtfHolding], Optional[str]]],
    default_output: str,
    tickers_example: Optional[str] = None,
    argv: Optional[List[str]] = None,
) -> None:
    """Shared CLI and orchestration for every provider fetcher's main().

    Every fetcher in this folder differs only in its provider name, its
    fetch_etf_list()/fetch_etf_holdings() pair, its default --output
    filename, and (for the --tickers help text) a couple of example
    tickers - everything else (the argument parser, --tickers/--limit
    filtering, the numbered progress loop with per-fund error isolation,
    the write_output() call and the summary print) is identical, so it
    lives here once instead of six times.

    argv defaults to sys.argv (via argparse) and is only overridable so
    tests can drive this without touching real command-line args.
    """
    parser = argparse.ArgumentParser(description=f"Scrape the list of {provider_name} ETFs and their holdings.")
    parser.add_argument("--output", default=default_output, help="Output JSON file")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay in seconds between holdings requests")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of ETFs processed (useful for testing)")
    tickers_help = "Only fetch these fund tickers"
    if tickers_example:
        tickers_help += f" (e.g. {tickers_example})"
    parser.add_argument("--tickers", nargs="+", metavar="ID", help=tickers_help)
    args = parser.parse_args(argv)

    with browser_session() as session:
        print(f"Fetching the {provider_name} ETF list...")
        if "delay" in inspect.signature(fetch_etf_list).parameters:
            # ark.py's fetch_etf_list makes one HTTP request per fund slug
            # to build the list, and paces those with the same --delay as
            # the holdings loop below; every other provider's
            # fetch_etf_list(session) takes no such parameter.
            funds = fetch_etf_list(session, delay=args.delay)
        else:
            funds = fetch_etf_list(session)
        print(f"{len(funds)} ETFs found.")

        if args.tickers:
            wanted = {t.strip().upper() for t in args.tickers}
            funds = [f for f in funds if f.ticker.upper() in wanted]
            missing = wanted - {f.ticker.upper() for f in funds}
            if missing:
                print(f"Not in the {provider_name} fund list: {', '.join(sorted(missing))}")
        if args.limit:
            funds = funds[: args.limit]

        results: List[EtfResult] = []
        for i, fund in enumerate(funds, start=1):
            print(f"[{i}/{len(funds)}] {fund.ticker} ({fund.name})...", end=" ", flush=True)
            try:
                holdings, note = fetch_etf_holdings(session, fund.holdings_url)
                results.append(EtfResult(etf_ticker=fund.ticker, etf_name=fund.name, holdings=holdings, note=note))
                if note:
                    print(f"OK - {note}")
                else:
                    print(f"OK ({len(holdings)} positions)")
            except Exception as exc:  # keep going even if one fund fails
                results.append(EtfResult(etf_ticker=fund.ticker, etf_name=fund.name, error=str(exc)))
                print(f"FAILED ({exc})")
            if i < len(funds):  # no need to wait after the last fund
                time.sleep(args.delay)

    write_output(results, args.output)

    ok = sum(1 for r in results if r.error is None)
    with_tickers = sum(1 for r in results if r.holdings)
    print(f"\nDone: {ok}/{len(results)} ETFs fetched without error, {with_tickers} with stock tickers extracted.")
    print(f"Output written to {args.output}")


class Response:
    """Adapts a Playwright APIResponse to the requests.Response surface
    each fetcher's parsing code already uses - .status_code/.headers/
    .content/.text/.json()/.raise_for_status() - so switching a fetcher
    from requests to BrowserSession is a matter of dropping the explicit
    headers= kwarg (baked into the browser context instead), not
    rewriting how responses get parsed. .headers keys are lowercased,
    matching how fetchers look them up (e.g. "content-type")."""

    def __init__(self, api_response):
        self._resp = api_response
        self.status_code = api_response.status
        self.headers = {k.lower(): v for k, v in api_response.headers.items()}

    @property
    def content(self) -> bytes:
        return self._resp.body()

    @property
    def text(self) -> str:
        # Decode ourselves rather than relying on APIResponse.text()'s own
        # charset sniffing, so behavior is the same (UTF-8) across every
        # fetcher regardless of what a given provider's Content-Type says.
        return self._resp.body().decode("utf-8", errors="replace")

    def json(self):
        return self._resp.json()

    def raise_for_status(self):
        if not self._resp.ok:
            raise RuntimeError(f"HTTP {self.status_code} for {self._resp.url}")


class BrowserSession:
    """Playwright-backed stand-in for requests.Session, offering two ways
    to reach a provider:

      .get(url, params=None, timeout=20.0) - a raw HTTP request through
      the browser context (real TLS/HTTP fingerprint, shared cookies), but
      no page is rendered and no JS runs. This is the default, lightweight
      path and is enough for every provider so far except one.

      .open_page(url) + .fetch_json(url, params=None) - for a provider
      whose API is gated behind an in-page bot-check/JS challenge that
      .get() alone can't satisfy (see fetcher/invesco.py's module
      docstring for how this was discovered): .open_page() loads a real
      page once so the site's own JS can run and resolve whatever check is
      in place, then .fetch_json() issues fetch() calls from *within*
      that page's JS engine - not a decoupled HTTP client - for as many
      URLs as needed, without reloading the page each time.
    """

    def __init__(self, playwright, headless: bool = True):
        self._browser = playwright.chromium.launch(headless=headless)
        self._context = self._browser.new_context(
            user_agent=HEADERS["User-Agent"],
            extra_http_headers={k: v for k, v in HEADERS.items() if k != "User-Agent"},
        )
        self._page = None

    def get(self, url: str, params: Optional[dict] = None, timeout: float = 20.0) -> Response:
        api_response = self._context.request.get(url, params=params, timeout=timeout * 1000)
        return Response(api_response)

    def open_page(self, url: str, timeout: float = 30.0) -> None:
        if self._page is None:
            self._page = self._context.new_page()
        self._page.goto(url, wait_until="networkidle", timeout=timeout * 1000)

    def fetch_json(
        self,
        url: str,
        params: Optional[Union[dict, list]] = None,
        timeout: float = 20.0,
    ) -> dict:
        if self._page is None:
            raise RuntimeError("fetch_json() requires open_page() to be called first on this session")

        full_url = f"{url}?{urlencode(params)}" if params else url
        result = self._page.evaluate(
            """async ({url, timeout}) => {
                const controller = new AbortController();
                const t = setTimeout(() => controller.abort(), timeout);
                try {
                    const r = await fetch(url, {signal: controller.signal});
                    return {status: r.status, body: await r.text()};
                } finally {
                    clearTimeout(t);
                }
            }""",
            {"url": full_url, "timeout": timeout * 1000},
        )
        if result["status"] != 200:
            raise RuntimeError(f"HTTP {result['status']} fetching {full_url}")
        return json.loads(result["body"])

    def close(self) -> None:
        self._context.close()
        self._browser.close()


@contextmanager
def browser_session(headless: bool = True):
    """Context manager yielding a BrowserSession:

        with browser_session() as session:
            funds = fetch_etf_list(session)
    """
    with sync_playwright() as p:
        session = BrowserSession(p, headless=headless)
        try:
            yield session
        finally:
            session.close()
