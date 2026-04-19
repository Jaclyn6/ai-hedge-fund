"""Pure analyzer functions for the quantitative fundamentals analyst.

Extracted from `fundamentals.py` so they can be imported without pulling in
LangChain / LangGraph. The original agent module can re-use these, and the MCP
server in `mcp_server/` imports from here directly.

4-axis quant scoring (profitability, growth, financial health, price ratios).
Signals are aggregated by majority vote across the 4 axes.
"""
from __future__ import annotations

from typing import Any


def analyze_profitability(metrics: Any) -> dict[str, Any]:
    """Score profitability on ROE, net margin, and operating margin."""
    roe = getattr(metrics, "return_on_equity", None)
    net_margin = getattr(metrics, "net_margin", None)
    op_margin = getattr(metrics, "operating_margin", None)

    thresholds = [
        (roe, 0.15),         # Strong ROE above 15%
        (net_margin, 0.20),  # Healthy profit margins
        (op_margin, 0.15),   # Strong operating efficiency
    ]
    score = sum(m is not None and m > t for m, t in thresholds)

    if score >= 2:
        signal = "bullish"
    elif score == 0:
        signal = "bearish"
    else:
        signal = "neutral"

    details = ", ".join([
        f"ROE: {roe:.2%}" if roe is not None else "ROE: N/A",
        f"Net Margin: {net_margin:.2%}" if net_margin is not None else "Net Margin: N/A",
        f"Op Margin: {op_margin:.2%}" if op_margin is not None else "Op Margin: N/A",
    ])
    return {"signal": signal, "score": score, "max_score": 3, "details": details}


def analyze_growth(metrics: Any) -> dict[str, Any]:
    """Score growth on revenue, earnings, and book-value growth."""
    rev_growth = getattr(metrics, "revenue_growth", None)
    eps_growth = getattr(metrics, "earnings_growth", None)
    bv_growth = getattr(metrics, "book_value_growth", None)

    thresholds = [
        (rev_growth, 0.10),
        (eps_growth, 0.10),
        (bv_growth, 0.10),
    ]
    score = sum(m is not None and m > t for m, t in thresholds)

    if score >= 2:
        signal = "bullish"
    elif score == 0:
        signal = "bearish"
    else:
        signal = "neutral"

    details = ", ".join([
        f"Revenue Growth: {rev_growth:.2%}" if rev_growth is not None else "Revenue Growth: N/A",
        f"Earnings Growth: {eps_growth:.2%}" if eps_growth is not None else "Earnings Growth: N/A",
    ])
    return {"signal": signal, "score": score, "max_score": 3, "details": details}


def analyze_financial_health(metrics: Any) -> dict[str, Any]:
    """Score balance-sheet strength on current ratio, D/E, and FCF conversion."""
    current_ratio = getattr(metrics, "current_ratio", None)
    debt_to_equity = getattr(metrics, "debt_to_equity", None)
    fcf_per_share = getattr(metrics, "free_cash_flow_per_share", None)
    eps = getattr(metrics, "earnings_per_share", None)

    score = 0
    if current_ratio is not None and current_ratio > 1.5:
        score += 1
    if debt_to_equity is not None and debt_to_equity < 0.5:
        score += 1
    if (
        fcf_per_share is not None
        and eps is not None
        and fcf_per_share > eps * 0.8
    ):
        score += 1

    if score >= 2:
        signal = "bullish"
    elif score == 0:
        signal = "bearish"
    else:
        signal = "neutral"

    details = ", ".join([
        f"Current Ratio: {current_ratio:.2f}" if current_ratio is not None else "Current Ratio: N/A",
        f"D/E: {debt_to_equity:.2f}" if debt_to_equity is not None else "D/E: N/A",
    ])
    return {"signal": signal, "score": score, "max_score": 3, "details": details}


def analyze_price_ratios(metrics: Any) -> dict[str, Any]:
    """Score valuation ratios — bearish when expensive on P/E, P/B, P/S."""
    pe = getattr(metrics, "price_to_earnings_ratio", None)
    pb = getattr(metrics, "price_to_book_ratio", None)
    ps = getattr(metrics, "price_to_sales_ratio", None)

    thresholds = [
        (pe, 25),
        (pb, 3),
        (ps, 5),
    ]
    # High ratios => expensive => bearish
    expensive_count = sum(m is not None and m > t for m, t in thresholds)

    if expensive_count >= 2:
        signal = "bearish"
    elif expensive_count == 0:
        signal = "bullish"
    else:
        signal = "neutral"

    details = ", ".join([
        f"P/E: {pe:.2f}" if pe is not None else "P/E: N/A",
        f"P/B: {pb:.2f}" if pb is not None else "P/B: N/A",
        f"P/S: {ps:.2f}" if ps is not None else "P/S: N/A",
    ])
    return {"signal": signal, "score": 3 - expensive_count, "max_score": 3, "details": details}


def analyze_fundamentals_quant(financial_metrics: list) -> dict[str, Any]:
    """Run the 4-axis quant fundamentals scoring and aggregate.

    Returns dict with top-level {signal, confidence, reasoning} where reasoning
    holds the four per-axis dicts keyed by {profitability, growth, financial_health,
    price_ratios}.
    """
    if not financial_metrics:
        return {
            "signal": "neutral",
            "confidence": 0,
            "reasoning": {},
            "details": "No financial metrics available",
        }

    metrics = financial_metrics[0]

    profitability = analyze_profitability(metrics)
    growth = analyze_growth(metrics)
    health = analyze_financial_health(metrics)
    price_ratios = analyze_price_ratios(metrics)

    signals = [profitability["signal"], growth["signal"], health["signal"], price_ratios["signal"]]
    bullish = signals.count("bullish")
    bearish = signals.count("bearish")

    if bullish > bearish:
        overall = "bullish"
    elif bearish > bullish:
        overall = "bearish"
    else:
        overall = "neutral"

    confidence = round(max(bullish, bearish) / len(signals) * 100)

    return {
        "signal": overall,
        "confidence": confidence,
        "reasoning": {
            "profitability_signal": profitability,
            "growth_signal": growth,
            "financial_health_signal": health,
            "price_ratios_signal": price_ratios,
        },
    }
