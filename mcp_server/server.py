"""MCP server exposing ai-hedge-fund's financial data and investor-style analyses.

Claude Code subagents (Buffett, Graham, etc.) call these tools to get
pre-computed fundamentals, moat analysis, intrinsic value, and margin of
safety — then synthesize a bullish/bearish/neutral signal natively, without
needing a separate LLM API key.

Run as: `python -m mcp_server.server`
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

# Make `src` importable when launched as a module from project root.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Load .env before importing src.tools.api, which reads DATA_SOURCE at module load.
from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from mcp.server.fastmcp import FastMCP

from src.tools.api import (
    get_company_news,
    get_financial_metrics,
    get_insider_trades,
    get_market_cap,
    get_prices,
    search_line_items,
)
from src.agents.warren_buffett_analysis import (
    analyze_book_value_growth,
    analyze_consistency,
    analyze_fundamentals,
    analyze_management_quality,
    analyze_moat,
    analyze_pricing_power,
    calculate_intrinsic_value,
)
from src.agents.ben_graham_analysis import (
    analyze_earnings_stability,
    analyze_financial_strength,
    analyze_valuation_graham,
)
from src.agents.charlie_munger_analysis import (
    analyze_moat_strength as munger_moat,
    analyze_management_quality as munger_mgmt,
    analyze_predictability as munger_predict,
    calculate_munger_valuation,
    analyze_news_sentiment as munger_news_sentiment,
)
from src.agents.michael_burry_analysis import (
    analyze_value as burry_value,
    analyze_balance_sheet as burry_balance,
    analyze_insider_activity as burry_insider,
    analyze_contrarian_sentiment as burry_contrarian,
    derive_preliminary_signal as burry_pre_signal,
)
from src.agents.bill_ackman_analysis import (
    analyze_business_quality as ackman_quality,
    analyze_financial_discipline as ackman_discipline,
    analyze_activism_potential as ackman_activism,
    analyze_valuation as ackman_valuation,
)
from src.agents.cathie_wood_analysis import (
    analyze_disruptive_potential as wood_disruptive,
    analyze_innovation_growth as wood_innovation,
    analyze_cathie_wood_valuation as wood_valuation,
)
from src.agents.peter_lynch_analysis import (
    analyze_lynch_growth,
    analyze_lynch_fundamentals,
    analyze_lynch_valuation,
    analyze_sentiment as lynch_sentiment,
    analyze_insider_activity as lynch_insider,
)

mcp = FastMCP("hedgefund")


# ──────────────────────────────────────────────────────────────────────────────
# Data-quality guardrail
# ──────────────────────────────────────────────────────────────────────────────
# Any phrase that, when found inside an analyzer's `details` string, signals
# that analyzer ran against incomplete data. These are the actual strings the
# analyzer functions emit today (see src/agents/*_analysis.py). Keep this list
# up to date when adding new investor analyzers.
_DEGRADATION_MARKERS = (
    "Insufficient data",
    "Insufficient historical",
    "Insufficient fundamental",
    "Insufficient book value",
    "Insufficient earnings",
    "not available",
    "data not available",
    "Cannot compute",
    "Unable to compute",
    # Specific "Limited X analysis available" phrases rather than bare "Limited"
    # (which would false-positive on any analyzer text containing "Limited").
    "Limited moat analysis",
    "Limited pricing power analysis",
    "No data",
    "Not enough multi-year EPS",
    "Missing components",
    "missing or invalid",
    "Missing or invalid",
)


def _has_degradation(details: str | None) -> bool:
    if not details or not isinstance(details, str):
        return False
    return any(marker.lower() in details.lower() for marker in _DEGRADATION_MARKERS)


def _assess_data_quality(
    analysis: dict,
    critical_fields: list[str],
    analyzer_keys: list[str],
) -> dict:
    """Inspect a consolidated analysis dict and produce a data-quality report.

    - `critical_fields`: top-level keys whose None value breaks the valuation
      decision (e.g. "market_cap", "intrinsic_value", "graham_number").
    - `analyzer_keys`: sub-dict keys holding per-analyzer `{score, details}`.
    """
    missing_fields = [f for f in critical_fields if analysis.get(f) is None]
    degraded_analyzers = []
    for key in analyzer_keys:
        sub = analysis.get(key)
        if not isinstance(sub, dict):
            continue
        if _has_degradation(sub.get("details")):
            degraded_analyzers.append({"name": key, "reason": sub.get("details")})

    critical = bool(missing_fields)
    complete = not critical and not degraded_analyzers

    warnings = []
    if missing_fields:
        warnings.append(
            f"CRITICAL: cannot complete valuation — missing fields: {', '.join(missing_fields)}"
        )
    for d in degraded_analyzers:
        warnings.append(f"{d['name']} ran against incomplete data: {d['reason']}")

    return {
        "complete": complete,
        "critical": critical,
        "missing_fields": missing_fields,
        "degraded_analyzers": degraded_analyzers,
        "warnings": warnings,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Raw data tools — mirror src.tools.api but return plain dicts for MCP transport
# ──────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def fetch_prices(ticker: str, start_date: str, end_date: str) -> list[dict]:
    """Daily OHLCV prices for a ticker. Dates are YYYY-MM-DD."""
    return [p.model_dump() for p in get_prices(ticker, start_date, end_date)]


@mcp.tool()
def fetch_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
) -> list[dict]:
    """Financial metrics (ROE, margins, ratios, growth) ending at end_date.

    period: 'ttm' | 'annual' | 'quarterly'. Most recent period first.
    """
    return [m.model_dump() for m in get_financial_metrics(ticker, end_date, period, limit)]


def _resolve_market_cap(ticker: str, end_date: str) -> float | None:
    """Real-time-first market cap resolution.

    Used when the user needs to know "is it good to buy at today's price?"
    rather than "what was this worth last quarter?" Uses a three-tier fallback:

    1. **Live**: `latest_close_price × outstanding_shares` using the most
       recent trading day ≤ end_date. Works on the free tier because the
       prices endpoint is open. Shares outstanding come from the most recent
       quarterly report — that changes slowly (buybacks / issuance take
       quarters), so pairing them with today's close gives an accurate live
       market cap.
    2. **V1 default**: `get_market_cap(ticker, end_date)`. Hits the company-
       facts endpoint when end_date == today (free tier returns null) or the
       financial-metrics endpoint otherwise (report-date value, can be months
       stale).
    3. **Last resort**: most recent `financial_metrics[0].market_cap` — same
       report-date value v1 falls to.
    """
    # Step 1: live close × shares (the "should I buy today" answer).
    # The prices endpoint rejects requests whose end_date is in the server's
    # future — and the server's "today" often lags the caller's clock by a
    # day (timezone). Always use end_date − 1 day as the price window's
    # upper bound and a 15-day window to guarantee at least one trading day.
    try:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        safe_end = (end_dt - timedelta(days=1)).strftime("%Y-%m-%d")
        window_start = (end_dt - timedelta(days=15)).strftime("%Y-%m-%d")
        prices = get_prices(ticker, window_start, safe_end)
        if prices:
            latest = max(prices, key=lambda p: p.time)
            line_items = search_line_items(
                ticker, ["outstanding_shares"], end_date, period="ttm", limit=1
            )
            if line_items and getattr(line_items[0], "outstanding_shares", None):
                return float(latest.close) * float(line_items[0].outstanding_shares)
    except Exception:
        pass  # fall through to v1 path

    # Step 2: v1 path
    mc = get_market_cap(ticker, end_date)
    if mc is not None:
        return mc

    # Step 3: financial-metrics fallback
    metrics = get_financial_metrics(ticker, end_date, period="ttm", limit=1)
    if metrics and metrics[0].market_cap:
        return metrics[0].market_cap
    return None


@mcp.tool()
def fetch_market_cap(ticker: str, end_date: str) -> float | None:
    """Market capitalization at end_date, or None if unavailable.

    Uses a fallback to the latest financial-metrics report when the
    current-day endpoint returns null (free-tier gate).
    """
    return _resolve_market_cap(ticker, end_date)


@mcp.tool()
def fetch_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
) -> list[dict]:
    """Specific financial statement line items.

    Examples: 'revenue', 'net_income', 'free_cash_flow', 'capital_expenditure',
    'shareholders_equity', 'outstanding_shares', 'gross_profit'.
    """
    return [item.model_dump() for item in search_line_items(ticker, line_items, end_date, period, limit)]


@mcp.tool()
def fetch_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Officer/director trading activity (SEC Form 4 filings)."""
    return [t.model_dump() for t in get_insider_trades(ticker, end_date, start_date, limit)]


@mcp.tool()
def fetch_company_news(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Company news headlines with optional sentiment labels."""
    return [n.model_dump() for n in get_company_news(ticker, end_date, start_date, limit)]


# ──────────────────────────────────────────────────────────────────────────────
# Buffett analysis — one-call convenience tool that runs every analyzer
# ──────────────────────────────────────────────────────────────────────────────

_BUFFETT_LINE_ITEMS = [
    "capital_expenditure",
    "depreciation_and_amortization",
    "net_income",
    "outstanding_shares",
    "total_assets",
    "total_liabilities",
    "shareholders_equity",
    "dividends_and_other_cash_distributions",
    "issuance_or_purchase_of_equity_shares",
    "gross_profit",
    "revenue",
    "free_cash_flow",
]


@mcp.tool()
def buffett_analysis(ticker: str, end_date: str) -> dict:
    """Run Warren Buffett's full fundamental analysis on a ticker.

    Fetches 10 periods of financial metrics + line items, then runs every
    Buffett analyzer: fundamentals (ROE, debt, margins, liquidity), consistency
    (earnings growth), moat (pricing power, ROE stability), pricing power
    (gross margin trends), book value growth, management quality (buybacks vs
    dilution), intrinsic value (three-stage DCF on owner earnings), margin of
    safety (intrinsic_value vs market_cap).

    Returns a structured dict: `score`, `max_score`, `intrinsic_value`,
    `market_cap`, `margin_of_safety`, plus per-analyzer score + details.
    Use this dict to decide bullish/bearish/neutral.
    """
    metrics = get_financial_metrics(ticker, end_date, period="ttm", limit=10)
    line_items = search_line_items(ticker, _BUFFETT_LINE_ITEMS, end_date, period="ttm", limit=10)
    market_cap = _resolve_market_cap(ticker, end_date)

    fundamental = analyze_fundamentals(metrics)
    consistency = analyze_consistency(line_items)
    moat = analyze_moat(metrics)
    pricing_power = analyze_pricing_power(line_items, metrics)
    book_value = analyze_book_value_growth(line_items)
    mgmt = analyze_management_quality(line_items)
    intrinsic = calculate_intrinsic_value(line_items)

    total_score = (
        fundamental.get("score", 0)
        + consistency.get("score", 0)
        + moat.get("score", 0)
        + mgmt.get("score", 0)
        + pricing_power.get("score", 0)
        + book_value.get("score", 0)
    )
    max_possible_score = (
        10  # fundamentals: ROE + debt + margins + current ratio
        + moat.get("max_score", 5)
        + mgmt.get("max_score", 2)
        + 5  # pricing power
        + 5  # book value growth
    )

    intrinsic_value = intrinsic.get("intrinsic_value")
    margin_of_safety = None
    if intrinsic_value and market_cap:
        margin_of_safety = (intrinsic_value - market_cap) / market_cap

    result = {
        "ticker": ticker,
        "end_date": end_date,
        "score": total_score,
        "max_score": max_possible_score,
        "market_cap": market_cap,
        "intrinsic_value": intrinsic_value,
        "margin_of_safety": margin_of_safety,
        "fundamental_analysis": fundamental,
        "consistency_analysis": consistency,
        "moat_analysis": moat,
        "pricing_power_analysis": pricing_power,
        "book_value_analysis": book_value,
        "management_analysis": mgmt,
        "intrinsic_value_analysis": intrinsic,
    }
    result["data_quality"] = _assess_data_quality(
        result,
        critical_fields=["market_cap", "intrinsic_value", "margin_of_safety"],
        analyzer_keys=[
            "fundamental_analysis",
            "consistency_analysis",
            "moat_analysis",
            "pricing_power_analysis",
            "book_value_analysis",
            "management_analysis",
            "intrinsic_value_analysis",
        ],
    )
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Ben Graham analysis — classic value investing: earnings stability, financial
# strength, and Graham Number valuation with margin of safety
# ──────────────────────────────────────────────────────────────────────────────

_GRAHAM_LINE_ITEMS = [
    "earnings_per_share",
    "revenue",
    "net_income",
    "book_value_per_share",
    "total_assets",
    "total_liabilities",
    "current_assets",
    "current_liabilities",
    "dividends_and_other_cash_distributions",
    "outstanding_shares",
]


@mcp.tool()
def graham_analysis(ticker: str, end_date: str) -> dict:
    """Run Benjamin Graham's classic value-investing analysis on a ticker.

    Fetches 10 annual periods of metrics + line items, then computes:
    - Earnings stability (consecutive positive-EPS years, EPS growth)
    - Financial strength (current ratio ≥ 2, debt/assets, dividend record)
    - Valuation (net-net check: NCAV vs market cap; Graham Number =
      sqrt(22.5 × EPS × BVPS); margin of safety vs Graham Number)

    Returns a structured dict: `score` (0-16), `max_score`, `graham_number`,
    `margin_of_safety`, `market_cap`, plus per-analyzer score + details.
    Use this dict to decide bullish/bearish/neutral.
    """
    metrics = get_financial_metrics(ticker, end_date, period="annual", limit=10)
    line_items = search_line_items(ticker, _GRAHAM_LINE_ITEMS, end_date, period="annual", limit=10)
    market_cap = _resolve_market_cap(ticker, end_date)

    earnings = analyze_earnings_stability(metrics, line_items)
    strength = analyze_financial_strength(line_items)
    valuation = analyze_valuation_graham(line_items, market_cap)

    total_score = earnings.get("score", 0) + strength.get("score", 0) + valuation.get("score", 0)
    max_possible_score = (
        earnings.get("max_score", 4)
        + strength.get("max_score", 5)
        + valuation.get("max_score", 7)
    )

    result = {
        "ticker": ticker,
        "end_date": end_date,
        "score": total_score,
        "max_score": max_possible_score,
        "market_cap": market_cap,
        "graham_number": valuation.get("graham_number"),
        "margin_of_safety": valuation.get("margin_of_safety"),
        "earnings_stability": earnings,
        "financial_strength": strength,
        "valuation_analysis": valuation,
    }
    result["data_quality"] = _assess_data_quality(
        result,
        critical_fields=["market_cap", "graham_number", "margin_of_safety"],
        analyzer_keys=["earnings_stability", "financial_strength", "valuation_analysis"],
    )
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Charlie Munger analysis — moat, management, predictability, Munger valuation
# ──────────────────────────────────────────────────────────────────────────────

_MUNGER_LINE_ITEMS = [
    "revenue",
    "net_income",
    "operating_income",
    "return_on_invested_capital",
    "gross_margin",
    "operating_margin",
    "free_cash_flow",
    "capital_expenditure",
    "cash_and_equivalents",
    "total_debt",
    "shareholders_equity",
    "outstanding_shares",
    "research_and_development",
    "goodwill_and_intangible_assets",
]


@mcp.tool()
def munger_analysis(ticker: str, end_date: str) -> dict:
    """Run Charlie Munger's mental-model-driven analysis on a ticker.

    Fetches 10 annual periods of metrics + line items + insider trades +
    recent news, then runs Munger's four analyzers: moat strength (ROIC
    consistency, pricing power, capital intensity, intangibles), management
    quality (capital allocation, debt discipline, cash hygiene, insider
    buying, share count), predictability (5-year revenue/op income/margin/
    FCF stability), and Munger valuation (normalized FCF × 10-20x multiple,
    margin of safety vs reasonable value).

    Quality-dominated weighting: 0.35 moat + 0.25 mgmt + 0.25 predictability
    + 0.15 valuation, scaled 0-10. High bar — score >= 7.5 for bullish,
    <= 5.5 for bearish, else neutral.

    Returns a structured dict matching the v1 `analysis_data[ticker]` shape,
    plus a `data_quality` block.
    """
    metrics = get_financial_metrics(ticker, end_date, period="annual", limit=10)
    line_items = search_line_items(ticker, _MUNGER_LINE_ITEMS, end_date, period="annual", limit=10)
    market_cap = _resolve_market_cap(ticker, end_date)
    insider_trades = get_insider_trades(ticker, end_date, limit=100)

    moat = munger_moat(metrics, line_items)
    mgmt = munger_mgmt(line_items, insider_trades)
    predict = munger_predict(line_items)
    valuation = calculate_munger_valuation(line_items, market_cap)

    # Munger's weighting — quality dominates (preserve v1 exactly)
    total_score = (
        moat.get("score", 0) * 0.35
        + mgmt.get("score", 0) * 0.25
        + predict.get("score", 0) * 0.25
        + valuation.get("score", 0) * 0.15
    )
    max_possible_score = 10  # analyzers already 0-10

    # Pre-compute signal per v1 rule (Munger's high standards)
    if total_score >= 7.5:
        pre_signal = "bullish"
    elif total_score <= 5.5:
        pre_signal = "bearish"
    else:
        pre_signal = "neutral"

    result = {
        "ticker": ticker,
        "end_date": end_date,
        "pre_signal": pre_signal,
        "score": round(total_score, 2),
        "max_score": max_possible_score,
        "market_cap": market_cap,
        "moat_analysis": moat,
        "management_analysis": mgmt,
        "predictability_analysis": predict,
        "valuation_analysis": valuation,
    }
    result["data_quality"] = _assess_data_quality(
        result,
        critical_fields=["market_cap"],
        analyzer_keys=["moat_analysis", "management_analysis", "predictability_analysis", "valuation_analysis"],
    )
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Michael Burry analysis — deep-value, contrarian, catalyst-aware
# ──────────────────────────────────────────────────────────────────────────────

_BURRY_LINE_ITEMS = [
    "free_cash_flow",
    "net_income",
    "total_debt",
    "cash_and_equivalents",
    "total_assets",
    "total_liabilities",
    "outstanding_shares",
    "issuance_or_purchase_of_equity_shares",
]


@mcp.tool()
def burry_analysis(ticker: str, end_date: str) -> dict:
    """Run Michael Burry's deep-value, contrarian analysis on a ticker.

    Four sub-analyses: value (FCF yield, EV/EBIT), balance sheet (leverage,
    cash), insider activity (net buying over trailing 12 months), contrarian
    sentiment (negative-headline count as a reverse signal).

    Preliminary signal from aggregate score ≥ 0.7·max → bullish, ≤ 0.3·max
    → bearish, else neutral (v1 rule). The subagent still makes the final
    call with Burry's voice.
    """
    metrics = get_financial_metrics(ticker, end_date, period="ttm", limit=5)
    line_items = search_line_items(ticker, _BURRY_LINE_ITEMS, end_date, period="ttm", limit=10)
    market_cap = _resolve_market_cap(ticker, end_date)

    # Burry looks one year back for insider trades + news
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_date = (end_dt - timedelta(days=365)).strftime("%Y-%m-%d")
    insider_trades = get_insider_trades(ticker, end_date, start_date=start_date, limit=1000)
    news = get_company_news(ticker, end_date, start_date=start_date, limit=250)

    value = burry_value(metrics, line_items, market_cap)
    balance = burry_balance(metrics, line_items)
    insider = burry_insider(insider_trades)
    contrarian = burry_contrarian(news)

    total_score = (
        value.get("score", 0)
        + balance.get("score", 0)
        + insider.get("score", 0)
        + contrarian.get("score", 0)
    )
    max_score = (
        value.get("max_score", 0)
        + balance.get("max_score", 0)
        + insider.get("max_score", 0)
        + contrarian.get("max_score", 0)
    )
    pre_signal = burry_pre_signal(total_score, max_score)

    result = {
        "ticker": ticker,
        "end_date": end_date,
        "pre_signal": pre_signal,
        "score": total_score,
        "max_score": max_score,
        "market_cap": market_cap,
        "value_analysis": value,
        "balance_sheet_analysis": balance,
        "insider_activity_analysis": insider,
        "contrarian_sentiment_analysis": contrarian,
    }
    result["data_quality"] = _assess_data_quality(
        result,
        critical_fields=["market_cap"],
        analyzer_keys=["value_analysis", "balance_sheet_analysis", "insider_activity_analysis", "contrarian_sentiment_analysis"],
    )
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Bill Ackman analysis — activist, high-quality businesses, concentrated bets
# ──────────────────────────────────────────────────────────────────────────────

_ACKMAN_LINE_ITEMS = [
    "revenue",
    "operating_margin",
    "debt_to_equity",
    "free_cash_flow",
    "total_assets",
    "total_liabilities",
    "dividends_and_other_cash_distributions",
    "outstanding_shares",
]


@mcp.tool()
def ackman_analysis(ticker: str, end_date: str) -> dict:
    """Run Bill Ackman's activist investor analysis on a ticker.

    Four sub-analyses: business quality (revenue growth, op margin, FCF
    consistency, ROE), financial discipline (debt/equity, liab/assets,
    buyback via share-count delta, dividends), activism potential
    (revenue growth + sub-par margin as catalyst trigger), valuation
    (DCF with 6% growth / 10% discount / 15x terminal).

    v1 signal thresholds: score ≥ 14/20 bullish, ≤ 6/20 bearish,
    else neutral.
    """
    metrics = get_financial_metrics(ticker, end_date, period="annual", limit=5)
    line_items = search_line_items(ticker, _ACKMAN_LINE_ITEMS, end_date, period="annual", limit=5)
    market_cap = _resolve_market_cap(ticker, end_date)

    quality = ackman_quality(metrics, line_items)
    discipline = ackman_discipline(metrics, line_items)
    activism = ackman_activism(line_items)
    valuation = ackman_valuation(line_items, market_cap)

    total_score = (
        quality.get("score", 0)
        + discipline.get("score", 0)
        + activism.get("score", 0)
        + valuation.get("score", 0)
    )
    max_score = 20  # v1: 5+5+5+5

    if total_score >= 14:
        pre_signal = "bullish"
    elif total_score <= 6:
        pre_signal = "bearish"
    else:
        pre_signal = "neutral"

    result = {
        "ticker": ticker,
        "end_date": end_date,
        "pre_signal": pre_signal,
        "score": total_score,
        "max_score": max_score,
        "market_cap": market_cap,
        "quality_analysis": quality,
        "discipline_analysis": discipline,
        "activism_analysis": activism,
        "valuation_analysis": valuation,
    }
    result["data_quality"] = _assess_data_quality(
        result,
        critical_fields=["market_cap"],
        analyzer_keys=["quality_analysis", "discipline_analysis", "activism_analysis", "valuation_analysis"],
    )
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Cathie Wood analysis — disruptive innovation, 5-year growth horizon
# ──────────────────────────────────────────────────────────────────────────────

_WOOD_LINE_ITEMS = [
    "revenue",
    "gross_margin",
    "operating_margin",
    "debt_to_equity",
    "free_cash_flow",
    "total_assets",
    "total_liabilities",
    "dividends_and_other_cash_distributions",
    "outstanding_shares",
    "research_and_development",
    "capital_expenditure",
    "operating_expense",
]


@mcp.tool()
def wood_analysis(ticker: str, end_date: str) -> dict:
    """Run Cathie Wood's disruptive-innovation analysis on a ticker.

    Three analyzers: disruptive potential (revenue acceleration, gross
    margin trajectory, R&D intensity, op leverage), innovation-driven
    growth (sustained high growth, capex, FCF reinvestment), and
    Wood-style DCF valuation (20% stage-1 growth, 15% discount rate,
    25x terminal — aggressive growth assumptions).
    """
    metrics = get_financial_metrics(ticker, end_date, period="annual", limit=5)
    line_items = search_line_items(ticker, _WOOD_LINE_ITEMS, end_date, period="annual", limit=5)
    market_cap = _resolve_market_cap(ticker, end_date)

    disruptive = wood_disruptive(metrics, line_items)
    innovation = wood_innovation(metrics, line_items)
    valuation = wood_valuation(line_items, market_cap)

    total_score = (
        disruptive.get("score", 0)
        + innovation.get("score", 0)
        + valuation.get("score", 0)
    )
    max_score = (
        disruptive.get("max_score", 0)
        + innovation.get("max_score", 0)
        + valuation.get("max_score", 0)
    )

    if max_score and total_score >= 0.7 * max_score:
        pre_signal = "bullish"
    elif max_score and total_score <= 0.3 * max_score:
        pre_signal = "bearish"
    else:
        pre_signal = "neutral"

    result = {
        "ticker": ticker,
        "end_date": end_date,
        "pre_signal": pre_signal,
        "score": total_score,
        "max_score": max_score,
        "market_cap": market_cap,
        "disruptive_analysis": disruptive,
        "innovation_analysis": innovation,
        "valuation_analysis": valuation,
    }
    result["data_quality"] = _assess_data_quality(
        result,
        critical_fields=["market_cap"],
        analyzer_keys=["disruptive_analysis", "innovation_analysis", "valuation_analysis"],
    )
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Peter Lynch analysis — GARP, ten-baggers, PEG-ratio focus
# ──────────────────────────────────────────────────────────────────────────────

_LYNCH_LINE_ITEMS = [
    "revenue",
    "earnings_per_share",
    "net_income",
    "operating_income",
    "gross_margin",
    "operating_margin",
    "free_cash_flow",
    "capital_expenditure",
    "cash_and_equivalents",
    "total_debt",
    "shareholders_equity",
    "outstanding_shares",
]


@mcp.tool()
def lynch_analysis(ticker: str, end_date: str) -> dict:
    """Run Peter Lynch's GARP (Growth At Reasonable Price) analysis on a ticker.

    Five analyzers: growth (revenue + EPS growth tiers), fundamentals
    (op margin, debt/equity, FCF quality), PEG-ratio valuation (P/E vs
    earnings growth rate), news sentiment (keyword-based), and insider
    activity (buy ratio).

    v1 signal thresholds on 0-10 composite: ≥ 7.5 bullish, ≤ 4.5 bearish,
    else neutral.
    """
    metrics = get_financial_metrics(ticker, end_date, period="annual", limit=5)
    line_items = search_line_items(ticker, _LYNCH_LINE_ITEMS, end_date, period="annual", limit=5)
    market_cap = _resolve_market_cap(ticker, end_date)

    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_date = (end_dt - timedelta(days=365)).strftime("%Y-%m-%d")
    insider_trades = get_insider_trades(ticker, end_date, start_date=start_date, limit=1000)
    news = get_company_news(ticker, end_date, start_date=start_date, limit=50)

    growth = analyze_lynch_growth(line_items)
    fundamentals = analyze_lynch_fundamentals(line_items)
    valuation = analyze_lynch_valuation(line_items, market_cap)
    sentiment = lynch_sentiment(news)
    insider = lynch_insider(insider_trades)

    # v1 weighted total -> 0-10 scale. Weights: growth 0.30, val 0.25,
    # fundamentals 0.20, sentiment 0.15, insider 0.10 (Lynch tilts toward
    # growth-at-reasonable-price, but see v1 for exact numbers)
    total_score = (
        growth.get("score", 0) * 0.30
        + valuation.get("score", 0) * 0.25
        + fundamentals.get("score", 0) * 0.20
        + sentiment.get("score", 0) * 0.15
        + insider.get("score", 0) * 0.10
    )
    max_score = 10

    if total_score >= 7.5:
        pre_signal = "bullish"
    elif total_score <= 4.5:
        pre_signal = "bearish"
    else:
        pre_signal = "neutral"

    result = {
        "ticker": ticker,
        "end_date": end_date,
        "pre_signal": pre_signal,
        "score": round(total_score, 2),
        "max_score": max_score,
        "market_cap": market_cap,
        "growth_analysis": growth,
        "fundamentals_analysis": fundamentals,
        "valuation_analysis": valuation,
        "sentiment_analysis": sentiment,
        "insider_analysis": insider,
    }
    result["data_quality"] = _assess_data_quality(
        result,
        critical_fields=["market_cap"],
        analyzer_keys=["growth_analysis", "fundamentals_analysis", "valuation_analysis", "sentiment_analysis", "insider_analysis"],
    )
    return result


if __name__ == "__main__":
    mcp.run()
