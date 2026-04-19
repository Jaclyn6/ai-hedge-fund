"""Pure analyzer functions for the growth-focused quantitative analyst.

Extracted from `growth_agent.py` so they can be imported without pulling in
LangChain / LangGraph. The original agent module can re-use these, and the MCP
server in `mcp_server/` imports from here directly.

5-factor weighted score:
    growth 40% + valuation 25% + margins 15% + insider 10% + health 10%

Signal thresholds: weighted_score > 0.6 bullish, < 0.4 bearish, else neutral.
"""
from __future__ import annotations

from typing import Any


def _calculate_trend(data: list[float | None]) -> float:
    """Slope of the trend line (simple linear regression) across non-None values."""
    clean = [d for d in data if d is not None]
    if len(clean) < 2:
        return 0.0

    y = clean
    x = list(range(len(y)))
    n = len(y)
    sum_x = sum(x)
    sum_y = sum(y)
    sum_xy = sum(i * j for i, j in zip(x, y))
    sum_x2 = sum(i * i for i in x)

    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return 0.0
    return (n * sum_xy - sum_x * sum_y) / denom


def analyze_growth_trends(metrics: list) -> dict[str, Any]:
    """Historical growth with trend acceleration detection."""
    rev_growth = [getattr(m, "revenue_growth", None) for m in metrics]
    eps_growth = [getattr(m, "earnings_per_share_growth", None) for m in metrics]
    fcf_growth = [getattr(m, "free_cash_flow_growth", None) for m in metrics]

    rev_trend = _calculate_trend(rev_growth)
    eps_trend = _calculate_trend(eps_growth)
    fcf_trend = _calculate_trend(fcf_growth)

    score = 0.0

    if rev_growth and rev_growth[0] is not None:
        if rev_growth[0] > 0.20:
            score += 0.4
        elif rev_growth[0] > 0.10:
            score += 0.2
        if rev_trend > 0:
            score += 0.1

    if eps_growth and eps_growth[0] is not None:
        if eps_growth[0] > 0.20:
            score += 0.25
        elif eps_growth[0] > 0.10:
            score += 0.1
        if eps_trend > 0:
            score += 0.05

    if fcf_growth and fcf_growth[0] is not None:
        if fcf_growth[0] > 0.15:
            score += 0.1

    score = min(score, 1.0)

    return {
        "score": score,
        "revenue_growth": rev_growth[0] if rev_growth else None,
        "revenue_trend": rev_trend,
        "eps_growth": eps_growth[0] if eps_growth else None,
        "eps_trend": eps_trend,
        "fcf_growth": fcf_growth[0] if fcf_growth else None,
        "fcf_trend": fcf_trend,
    }


def analyze_growth_valuation(metrics: Any) -> dict[str, Any]:
    """Growth-adjusted valuation via PEG + P/S."""
    peg = getattr(metrics, "peg_ratio", None)
    ps = getattr(metrics, "price_to_sales_ratio", None)

    score = 0.0
    if peg is not None:
        if peg < 1.0:
            score += 0.5
        elif peg < 2.0:
            score += 0.25

    if ps is not None:
        if ps < 2.0:
            score += 0.5
        elif ps < 5.0:
            score += 0.25

    score = min(score, 1.0)

    return {
        "score": score,
        "peg_ratio": peg,
        "price_to_sales_ratio": ps,
    }


def analyze_margin_trends(metrics: list) -> dict[str, Any]:
    """Margin-expansion detector across gross, operating, and net margins."""
    gross_margins = [getattr(m, "gross_margin", None) for m in metrics]
    operating_margins = [getattr(m, "operating_margin", None) for m in metrics]
    net_margins = [getattr(m, "net_margin", None) for m in metrics]

    gm_trend = _calculate_trend(gross_margins)
    om_trend = _calculate_trend(operating_margins)
    nm_trend = _calculate_trend(net_margins)

    score = 0.0

    if gross_margins and gross_margins[0] is not None:
        if gross_margins[0] > 0.5:
            score += 0.2
        if gm_trend > 0:
            score += 0.2

    if operating_margins and operating_margins[0] is not None:
        if operating_margins[0] > 0.15:
            score += 0.2
        if om_trend > 0:
            score += 0.2

    if nm_trend > 0:
        score += 0.2

    score = min(score, 1.0)

    return {
        "score": score,
        "gross_margin": gross_margins[0] if gross_margins else None,
        "gross_margin_trend": gm_trend,
        "operating_margin": operating_margins[0] if operating_margins else None,
        "operating_margin_trend": om_trend,
        "net_margin": net_margins[0] if net_margins else None,
        "net_margin_trend": nm_trend,
    }


def analyze_insider_conviction(trades: list) -> dict[str, Any]:
    """Net insider flow ratio: (buys - sells) / (buys + sells)."""
    buys = 0.0
    sells = 0.0
    for t in trades or []:
        value = getattr(t, "transaction_value", None)
        shares = getattr(t, "transaction_shares", None)
        if value is None or shares is None:
            continue
        if shares > 0:
            buys += value
        elif shares < 0:
            sells += abs(value)

    total = buys + sells
    net_flow_ratio = 0.0 if total == 0 else (buys - sells) / total

    if net_flow_ratio > 0.5:
        score = 1.0
    elif net_flow_ratio > 0.1:
        score = 0.7
    elif net_flow_ratio > -0.1:
        score = 0.5
    else:
        score = 0.2

    return {
        "score": score,
        "net_flow_ratio": net_flow_ratio,
        "buys": buys,
        "sells": sells,
    }


def check_financial_health(metrics: Any) -> dict[str, Any]:
    """Penalize high D/E and low current ratio; start at 1.0 and subtract."""
    debt_to_equity = getattr(metrics, "debt_to_equity", None)
    current_ratio = getattr(metrics, "current_ratio", None)

    score = 1.0
    if debt_to_equity is not None:
        if debt_to_equity > 1.5:
            score -= 0.5
        elif debt_to_equity > 0.8:
            score -= 0.2

    if current_ratio is not None:
        if current_ratio < 1.0:
            score -= 0.5
        elif current_ratio < 1.5:
            score -= 0.2

    score = max(score, 0.0)

    return {
        "score": score,
        "debt_to_equity": debt_to_equity,
        "current_ratio": current_ratio,
    }


def analyze_growth_combined(
    financial_metrics: list,
    insider_trades: list,
) -> dict[str, Any]:
    """Run all 5 sub-analyzers and combine with the v1 weighting.

    Requires at least 4 periods of financial_metrics to compute trends reliably.
    """
    if not financial_metrics or len(financial_metrics) < 4:
        return {
            "signal": "neutral",
            "confidence": 0,
            "reasoning": {
                "data_warning": "Insufficient data: fewer than 4 periods of financial metrics available",
            },
        }

    most_recent = financial_metrics[0]

    growth = analyze_growth_trends(financial_metrics)
    valuation = analyze_growth_valuation(most_recent)
    margins = analyze_margin_trends(financial_metrics)
    insider = analyze_insider_conviction(insider_trades or [])
    health = check_financial_health(most_recent)

    weights = {
        "growth": 0.40,
        "valuation": 0.25,
        "margins": 0.15,
        "insider": 0.10,
        "health": 0.10,
    }
    scores = {
        "growth": growth["score"],
        "valuation": valuation["score"],
        "margins": margins["score"],
        "insider": insider["score"],
        "health": health["score"],
    }

    weighted_score = sum(scores[k] * weights[k] for k in scores)

    if weighted_score > 0.6:
        signal = "bullish"
    elif weighted_score < 0.4:
        signal = "bearish"
    else:
        signal = "neutral"

    confidence = round(abs(weighted_score - 0.5) * 2 * 100)

    return {
        "signal": signal,
        "confidence": confidence,
        "reasoning": {
            "historical_growth": growth,
            "growth_valuation": valuation,
            "margin_expansion": margins,
            "insider_conviction": insider,
            "financial_health": health,
            "final_analysis": {
                "signal": signal,
                "confidence": confidence,
                "weighted_score": round(weighted_score, 2),
            },
        },
    }
