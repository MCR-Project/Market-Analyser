"""
Unit tests for fetcher/common.py's run_fetcher() - the shared CLI and
orchestration helper behind every provider fetcher's main() (--tickers/
--limit filtering, the numbered progress loop with per-fund error
isolation, and skipping the delay after the last fund). Exercised with
fake fetch_etf_list/fetch_etf_holdings callables and a stubbed-out
browser_session(), so no real browser or network access is involved.
"""

import json
from contextlib import contextmanager

import pytest

import common
from common import EtfFund, EtfHolding, run_fetcher

FUNDS = [
    EtfFund(ticker="AAA", name="Fund AAA", product_url="", holdings_url="aaa"),
    EtfFund(ticker="BBB", name="Fund BBB", product_url="", holdings_url="bbb"),
    EtfFund(ticker="CCC", name="Fund CCC", product_url="", holdings_url="ccc"),
]


@pytest.fixture(autouse=True)
def fake_browser_session(monkeypatch):
    """run_fetcher only ever passes the session through to the fake fetch_*
    callables below, which ignore it - a plain sentinel is enough, and
    avoids launching a real Playwright browser for what's otherwise a pure
    unit test of the filtering/looping/error-isolation logic."""

    @contextmanager
    def _fake_session():
        yield object()

    monkeypatch.setattr(common, "browser_session", _fake_session)


def _fetch_etf_list(session):
    return list(FUNDS)


def _make_fetch_etf_holdings(fail_for=frozenset()):
    def fetch_etf_holdings(session, holdings_url):
        if holdings_url in fail_for:
            raise RuntimeError(f"boom: {holdings_url}")
        return [EtfHolding(ticker=holdings_url.upper(), name="x", weight_pct=1.0)], None

    return fetch_etf_holdings


def _run(tmp_path, argv, fail_for=frozenset()):
    output = tmp_path / "out.json"
    run_fetcher(
        provider_name="Test",
        fetch_etf_list=_fetch_etf_list,
        fetch_etf_holdings=_make_fetch_etf_holdings(fail_for=fail_for),
        default_output=str(output),
        argv=argv,
    )
    return json.loads(output.read_text(encoding="utf-8"))


def test_tickers_filters_the_fund_list(tmp_path):
    data = _run(tmp_path, ["--tickers", "aaa", "ccc", "--delay", "0"])

    assert {e["ticker"] for e in data["etfs"]} == {"AAA", "CCC"}


def test_limit_applies_after_tickers_filtering(tmp_path):
    data = _run(tmp_path, ["--tickers", "aaa", "bbb", "ccc", "--limit", "2", "--delay", "0"])

    assert [e["ticker"] for e in data["etfs"]] == ["AAA", "BBB"]


def test_a_failing_fund_is_isolated_and_recorded_with_an_error(tmp_path):
    data = _run(tmp_path, ["--delay", "0"], fail_for={"bbb"})

    by_ticker = {e["ticker"]: e for e in data["etfs"]}
    assert by_ticker["AAA"]["error"] is None
    assert by_ticker["BBB"]["error"] == "boom: bbb"
    assert by_ticker["CCC"]["error"] is None
    # The failed fund still gets written out, with no holdings.
    assert by_ticker["BBB"]["holdings"] == []


def test_no_delay_is_slept_after_the_last_fund(tmp_path, monkeypatch):
    sleeps = []
    monkeypatch.setattr(common.time, "sleep", lambda s: sleeps.append(s))

    _run(tmp_path, ["--delay", "1.5"])

    # 3 funds -> 2 delays (after the 1st and 2nd), none after the 3rd.
    assert sleeps == [1.5, 1.5]


def test_fetch_etf_list_receives_delay_only_when_it_accepts_one(tmp_path):
    """ark.py's fetch_etf_list(session, delay=...) paces its own per-fund
    page requests while building the list, and must keep receiving
    --delay; every other provider's fetch_etf_list(session) takes no such
    parameter and must not be called with one."""
    received = {}

    def fetch_etf_list_with_delay(session, delay=0.0):
        received["delay"] = delay
        return list(FUNDS)

    output = tmp_path / "out.json"
    run_fetcher(
        provider_name="Test",
        fetch_etf_list=fetch_etf_list_with_delay,
        fetch_etf_holdings=_make_fetch_etf_holdings(),
        default_output=str(output),
        argv=["--delay", "2.5"],
    )

    assert received["delay"] == 2.5


def test_tickers_help_text_includes_the_example_when_given(capsys):
    with pytest.raises(SystemExit):
        run_fetcher(
            provider_name="Test",
            fetch_etf_list=_fetch_etf_list,
            fetch_etf_holdings=_make_fetch_etf_holdings(),
            default_output="unused.json",
            tickers_example="AAA BBB",
            argv=["--help"],
        )

    assert "e.g. AAA BBB" in capsys.readouterr().out
