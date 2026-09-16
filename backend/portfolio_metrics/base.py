"""
Base class for every portfolio metric tile (issue #104).

`services/portfolio.py`'s `_metrics()` and `PortfolioSummary.jsx`'s
hand-written grid used to be the only two places a metric's label, family,
null rule and description lived, kept in sync by hand. This is the
self-describing unit the measurement plugin system already demonstrates,
applied to the portfolio summary: a class per metric, a manifest endpoint,
and a frontend that builds its tiles and its enable/disable dialog from
whatever it finds - adding a metric costs one file and one `.mdx`, not a
backend edit, a frontend edit and a README edit kept in sync by hand.

**The arithmetic itself does not move here.** `services/portfolio.py` and
`services/stats.py` still own every number in `POST /api/portfolio/simulate`'s
response, unchanged (issue #104 is explicit: "arithmetic and response keys
do not change; existing tests stay as they are"). A metric class's `value()`
reads its own figure back out of that already-computed response - it is a
thin, self-describing label over an existing key, not a second
implementation of it. Duplicating the arithmetic here would be exactly the
kind of drift issue #98 moved it out of this file to prevent in the first
place.

Every entry declares what it is computed from (issue #104's own words):

  - `computed_from = "run"` - a completed `simulate_portfolio()` response.
    Every metric shipped today is this kind; `value()`'s default
    implementation reads `data["metrics"][self.id]`, which is correct for
    all twelve without an override.
  - `computed_from = "etf_id"` - a fund, not a run (issue #105's own
    three metrics: diversificationRatio, top5VarianceShare,
    trackedWeightCoverage). `value()` is called with the etf_id string
    itself and does its own computation - typically a thin read of
    `services.fund_metrics.compute_fund_metrics(etf_id)`'s own key, the
    fund-level mirror of `RunMetric.value()` reading a key out of a
    completed run. Such an entry must override `value()`; the base
    implementation only knows how to read a run. It may also override
    `reason()` (below) to explain a null value - there is no shared
    "reasons" response to read from the way a run's own
    `metrics["reasons"]` supplies one.
  - `computed_from = "risk"` - a completed `POST /api/portfolio/risk`
    response (issue #113's own three: averageCorrelation, effectiveBets,
    riskShare), the same basket shape a run is, but read from its own
    endpoint rather than folded into `simulate`'s - see that route's own
    docstring for why. `value()`'s default implementation (`RiskMetric`
    below) reads `data[self.id]`, the risk-response counterpart to
    `RunMetric` reading `data["metrics"][self.id]` out of a run.
"""

import inspect
from abc import ABC, abstractmethod
from pathlib import Path

# The two families every metric shipped today belongs to, plus the
# dividend note's non-tile family - declared here, not in the frontend, so
# the time-weighted/money-weighted row headers PortfolioSummary.jsx prints
# are read off the manifest rather than hardcoded (issue #104's own
# decision). Keyed the same as MetricBase.family.
FAMILIES = {
    "portfolio": {
        "label": "The portfolio",
        "note": "Time-weighted, so deposits do not count as gains",
    },
    "account": {
        "label": "The account",
        "note": "Money-weighted, so when each dollar arrived counts",
    },
    "dividend": {
        "label": "Dividends",
        "note": "Already inside every value above — reported, never added",
    },
    # The two computed_from="etf_id" families (issue #105) - properties of
    # a fund's whole basket, not of any one holding or any one run.
    "diversification": {
        "label": "Diversification",
        "note": "How independently the fund's holdings actually move",
    },
    "coverage": {
        "label": "Coverage",
        "note": "What the 1% tracking threshold leaves out of these figures",
    },
    # The computed_from="risk" family (issue #113) - a basket's own
    # diversification, read from POST /api/portfolio/risk rather than a
    # run's response, so it is a family in its own right rather than a
    # member of "diversification" above (which is scoped to a fund's
    # basket, not a simulated one).
    "risk": {
        "label": "Diversification",
        "note": "This basket's own holdings, read from its own endpoint only when enabled",
    },
}


class MetricBase(ABC):
    """Abstract base for portfolio metric tiles."""

    # ── Identity ─────────────────────────────────────────────────────────
    id: str = ""
    name: str = ""
    # Short label for the summary tile itself - a metric's own
    # column_label, mirroring MeasurementBase's distinction between a
    # full `name` (the dialog, the sidebar, the doc page) and a compact
    # one for a small, fixed-width space. Empty means "use name" - most
    # metrics' names are already short enough not to need a second one.
    tile_label: str = ""
    description: str = ""
    family: str = ""            # a key of FAMILIES above
    formula: str = ""           # short, human-readable, not necessarily LaTeX
    null_rule: str = ""         # when/why this metric is null instead of a number

    # How PortfolioSummary.jsx should draw this metric's value - the
    # portfolio-metric equivalent of a measurement's render_cell, kept to
    # a small fixed vocabulary rather than backend-authored MDX (issue
    # #104 does not ask for that machinery here, and a tile is a single
    # number, not a table cell needing a Bar/Badge). "currency" ($1,234),
    # "currency_signed" (+$1,234 / −$1,234, tone-coloured), "percent"
    # (12.3%), "percent_signed" (+12.3% / −12.3%, tone-coloured),
    # "drawdown" (a {value, peakDate, troughDate} object), "list"
    # (incomeUnknownFor's ticker list, joined for display), "ratio"
    # (1.42×, issue #105's diversificationRatio; issue #112's own
    # Calmar/Sharpe/Sortino share it, read by PortfolioSummary.jsx rather
    # than FundMetricsCard.jsx since they are computed_from="run"; issue
    # #113's own effectiveBets shares it too), "days" (45d, issue #112's
    # timeUnderWater), "correlation" (a bare signed decimal like 0.42 or
    # -0.15 - issue #113's own averageCorrelation - deliberately not
    # "percent"/"percent_signed": a negative reading here is not a loss
    # the way a negative return is, so tone-colouring it red would
    # misstate it). Adding a metric whose shape already fits one of these
    # needs no frontend change at all - not just to appear in the dialog,
    # but to render correctly as a tile too - **except** a
    # computed_from="risk" entry, which neither PortfolioSummary.jsx nor
    # FundMetricsCard.jsx renders at all: PortfolioRiskCard.jsx is the
    # one place "ratio" and "correlation" meet a "risk" value (see
    # computed_from below).
    format: str = "currency"

    # Which set this was registered in. Set by portfolio_metrics/__init__.py
    # the same way measurements/__init__.py stamps `origin` - kept for
    # DocsSidebar to group on, and so a portfolio metric's manifest row
    # looks like a measurement column's own wherever the two are merged.
    origin: str = "portfolio"

    # ── Attribution (issue #114) ─────────────────────────────────────────
    # Who wrote this metric, where to read more, and which version it is -
    # empty by default, and deliberately never defaulted to the repository
    # owner: an unattributed metric shows as unattributed. A doc's own
    # frontmatter (author/author_url/version - portfolio_metrics/docs.py)
    # overrides these three, the same precedence example_etf/
    # example_portfolio above already follow. Mirrors measurements/base.py
    # exactly, so the same AttributionCard renders either registry's
    # entries without needing to know which one it is looking at.
    author: str = ""
    author_url: str = ""
    version: str = ""

    # Whether PortfolioSummary renders this as a toggleable tile at all.
    # False for dividendIncome/dividendYield/incomeUnknownFor: the dividend
    # note stays prose (issue #68), not a tile - a decision this issue
    # explicitly keeps rather than reworks. A non-tile entry still gets a
    # manifest row and a doc page; it just never appears in the enable/
    # disable dialog, since there is nothing there to enable or disable.
    tile: bool = True
    default_enabled: bool = True

    # ── What this entry needs to be computed ────────────────────────────
    computed_from: str = "run"  # "run" | "etf_id" (issue #105) | "risk" (issue #113)

    # Overrides for the worked example, mirroring MeasurementBase's
    # example_etf/example_stock: a metric class may name its own rather
    # than take the repo-wide default in config.py. example_portfolio is
    # for a computed_from="run" entry (a dict shaped like
    # config.DOCS_EXAMPLE_PORTFOLIO); example_etf is for a computed_from=
    # "etf_id" one, and is deliberately the same field name/meaning
    # MeasurementBase already uses, since that kind of entry's example
    # really is just an ETF to run itself against.
    example_portfolio: dict | None = None
    example_etf: str = ""

    @abstractmethod
    def value(self, data):
        """This metric's own figure, read out of `data`.

        `data` is a completed simulate_portfolio() response for a
        computed_from="run" entry, or an etf_id string for a
        computed_from="etf_id" one. Subclasses of every metric shipped
        today do not need to implement this - see `RunMetric` below,
        which every official metric actually extends - but the base class
        stays abstract so a future etf_id-based entry cannot forget to.
        """
        ...

    def reason(self, data) -> str | None:
        """Why this metric's value came back null for `data`, if this
        entry knows - the computed_from="etf_id" counterpart to a run's
        own `metrics["reasons"]` entry (issue #99), used only by
        `examples.py`'s worked example for that branch. A `computed_from
        ="run"` entry never needs to override this: its reason travels
        inside the run itself, which `examples.py`'s "run" branch already
        reads directly. `None` by default - a metric with nothing to say
        about its own null returns none, the same "optional, not every
        metric needs one" rule `per_ticker_reason` follows.
        """
        return None

    # ── Documentation ────────────────────────────────────────────────────

    @property
    def doc_path(self) -> Path:
        """Where this metric's .mdx doc lives: its own module, .mdx - the
        same convention MeasurementBase.doc_path follows, for the same
        reason (an addon-shaped metric, if this ever grows one, gets it
        for free)."""
        return Path(inspect.getfile(type(self))).with_suffix(".mdx")

    @property
    def has_doc(self) -> bool:
        return self.doc_path.is_file()

    def manifest(self) -> dict:
        """Self-describing metadata for the registry endpoint."""
        return {
            "id": self.id,
            "name": self.name,
            "tile_label": self.tile_label or self.name,
            "description": self.description,
            "family": self.family,
            "formula": self.formula,
            "null_rule": self.null_rule,
            "format": self.format,
            "origin": self.origin,
            "tile": self.tile,
            "default_enabled": self.default_enabled,
            "computed_from": self.computed_from,
            "has_doc": self.has_doc,
            # The class's own, unresolved declaration (issue #114) -
            # registry.py overlays the doc-frontmatter-resolved version
            # on top before this ever reaches a caller, mirroring
            # measurements/base.py's own manifest() exactly.
            "author": self.author,
            "author_url": self.author_url,
            "version": self.version,
        }


class RunMetric(MetricBase):
    """A metric read straight out of a completed simulate_portfolio()
    response - what every metric shipped today is. `value()` needs no
    override: `self.id` is already the exact key `services/portfolio.py`'s
    `_metrics()` writes (finalValue, totalReturn, ...), by construction -
    migrating a metric here never renames its response key (issue #104).
    """

    computed_from = "run"

    def value(self, data):
        return (data.get("metrics") or {}).get(self.id)


class RiskMetric(MetricBase):
    """A metric read straight out of a completed `POST /api/portfolio/
    risk` response (issue #113) - `RunMetric`'s counterpart for that
    endpoint's own three entries. `value()` needs no override: `self.id`
    is already the exact top-level key `services/portfolio.py`'s
    `compute_portfolio_risk()` writes (averageCorrelation, effectiveBets,
    riskShare) - there is no "metrics" wrapper to unpack the way a run's
    response has, since the risk response *is* the metrics.
    """

    computed_from = "risk"

    def value(self, data):
        return (data or {}).get(self.id)
