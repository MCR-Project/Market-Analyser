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
"""

import json
import time
from dataclasses import dataclass, field
from typing import List, Optional

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
