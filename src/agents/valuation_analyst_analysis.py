"""Pure analyzer functions for the quantitative valuation analyst.

Extracted from `valuation.py` so they can be imported without pulling in
LangChain / LangGraph. The original agent module can re-use these, and the MCP
server in `mcp_server/` imports from here directly.

Four complementary valuation methodologies aggregated by weight:

    DCF scenarios (35%) + Owner earnings (35%) + EV/EBITDA (20%) + RIM (10%)

Signal thresholds: weighted_gap > +15% bullish, < -15% bearish, else neutral.
Confidence = min(|gap| / 30% * 100, 100).
"""
from __future__ import annotations

import statistics
from typing import Any


# ---------------------------------------------------------------------------
# Individual valuation methodologies
# ---------------------------------------------------------------------------


def calculate_owner_earnings_value(
    net_income: float | None,
    depreciation: float | None,
    capex: float | None,
    working_capital_change: float | None,
    growth_rate: float = 0.05,
    required_return: float = 0.15,
    margin_of_safety: float = 0.25,
    num_years: int = 5,
) -> float:
    """Buffett owner-earnings valuation with margin-of-safety applied."""
    if not all(
        isinstance(x, (int, float))
        for x in [net_income, depreciation, capex, working_capital_change]
    ):
        return 0.0

    owner_earnings = net_income + depreciation - capex - working_capital_change
    if owner_earnings <= 0:
        return 0.0

    pv = 0.0
    for yr in range(1, num_years + 1):
        future = owner_earnings * (1 + growth_rate) ** yr
        pv += future / (1 + required_return) ** yr

    terminal_growth = min(growth_rate, 0.03)
    term_val = (
        owner_earnings
        * (1 + growth_rate) ** num_years
        * (1 + terminal_growth)
    ) / (required_return - terminal_growth)
    pv_term = term_val / (1 + required_return) ** num_years

    intrinsic = pv + pv_term
    return intrinsic * (1 - margin_of_safety)


def calculate_intrinsic_value(
    free_cash_flow: float | None,
    growth_rate: float = 0.05,
    discount_rate: float = 0.10,
    terminal_growth_rate: float = 0.02,
    num_years: int = 5,
) -> float:
    """Classic DCF on FCF with constant growth and terminal value."""
    if free_cash_flow is None or free_cash_flow <= 0:
        return 0.0

    pv = 0.0
    for yr in range(1, num_years + 1):
        fcft = free_cash_flow * (1 + growth_rate) ** yr
        pv += fcft / (1 + discount_rate) ** yr

    term_val = (
        free_cash_flow
        * (1 + growth_rate) ** num_years
        * (1 + terminal_growth_rate)
    ) / (discount_rate - terminal_growth_rate)
    pv_term = term_val / (1 + discount_rate) ** num_years

    return pv + pv_term


def calculate_ev_ebitda_value(financial_metrics: list) -> float:
    """Implied equity value via median EV/EBITDA multiple."""
    if not financial_metrics:
        return 0.0
    m0 = financial_metrics[0]
    ev = getattr(m0, "enterprise_value", None)
    ev_ebitda = getattr(m0, "enterprise_value_to_ebitda_ratio", None)
    if not ev or not ev_ebitda or ev_ebitda == 0:
        return 0.0

    ebitda_now = ev / ev_ebitda
    multiples = [
        getattr(m, "enterprise_value_to_ebitda_ratio", None)
        for m in financial_metrics
        if getattr(m, "enterprise_value_to_ebitda_ratio", None)
    ]
    if not multiples:
        return 0.0
    med_mult = statistics.median(multiples)
    ev_implied = med_mult * ebitda_now
    mcap = getattr(m0, "market_cap", None) or 0
    net_debt = (ev or 0) - mcap
    return max(ev_implied - net_debt, 0.0)


def calculate_residual_income_value(
    market_cap: float | None,
    net_income: float | None,
    price_to_book_ratio: float | None,
    book_value_growth: float = 0.03,
    cost_of_equity: float = 0.10,
    terminal_growth_rate: float = 0.03,
    num_years: int = 5,
) -> float:
    """Residual Income Model (Edwards-Bell-Ohlson) with 20% margin of safety."""
    if not (
        market_cap
        and net_income
        and price_to_book_ratio
        and price_to_book_ratio > 0
    ):
        return 0.0

    book_val = market_cap / price_to_book_ratio
    ri0 = net_income - cost_of_equity * book_val
    if ri0 <= 0:
        return 0.0

    pv_ri = 0.0
    for yr in range(1, num_years + 1):
        ri_t = ri0 * (1 + book_value_growth) ** yr
        pv_ri += ri_t / (1 + cost_of_equity) ** yr

    term_ri = ri0 * (1 + book_value_growth) ** (num_years + 1) / (
        cost_of_equity - terminal_growth_rate
    )
    pv_term = term_ri / (1 + cost_of_equity) ** num_years

    intrinsic = book_val + pv_ri + pv_term
    return intrinsic * 0.8


# ---------------------------------------------------------------------------
# Enhanced DCF with WACC + scenarios
# ---------------------------------------------------------------------------


def calculate_wacc(
    market_cap: float,
    total_debt: float | None,
    cash: float | None,
    interest_coverage: float | None,
    debt_to_equity: float | None,
    beta_proxy: float = 1.0,
    risk_free_rate: float = 0.045,
    market_risk_premium: float = 0.06,
) -> float:
    """WACC estimate using CAPM for equity and interest-coverage proxy for debt."""
    cost_of_equity = risk_free_rate + beta_proxy * market_risk_premium

    if interest_coverage and interest_coverage > 0:
        cost_of_debt = max(risk_free_rate + 0.01, risk_free_rate + (10 / interest_coverage))
    else:
        cost_of_debt = risk_free_rate + 0.05

    net_debt = max((total_debt or 0) - (cash or 0), 0)
    total_value = market_cap + net_debt

    if total_value > 0:
        w_e = market_cap / total_value
        w_d = net_debt / total_value
        wacc = (w_e * cost_of_equity) + (w_d * cost_of_debt * 0.75)  # 25% tax shield
    else:
        wacc = cost_of_equity

    return min(max(wacc, 0.06), 0.20)


def calculate_fcf_volatility(fcf_history: list[float]) -> float:
    """FCF coefficient of variation — capped to [0, 1]."""
    if len(fcf_history) < 3:
        return 0.5

    positive = [fcf for fcf in fcf_history if fcf > 0]
    if len(positive) < 2:
        return 0.8

    try:
        mean_fcf = statistics.mean(positive)
        std_fcf = statistics.stdev(positive)
        return min(std_fcf / mean_fcf, 1.0) if mean_fcf > 0 else 0.8
    except statistics.StatisticsError:
        return 0.5


def calculate_enhanced_dcf_value(
    fcf_history: list[float],
    growth_metrics: dict,
    wacc: float,
    market_cap: float,
    revenue_growth: float | None = None,
) -> float:
    """Three-stage DCF (high growth / transition / terminal) with quality adjustment."""
    if not fcf_history or fcf_history[0] <= 0:
        return 0.0

    fcf_current = fcf_history[0]
    fcf_avg_3yr = sum(fcf_history[:3]) / min(3, len(fcf_history))
    fcf_volatility = calculate_fcf_volatility(fcf_history)

    high_growth = min(revenue_growth or 0.05, 0.25) if revenue_growth else 0.05
    if market_cap > 50_000_000_000:
        high_growth = min(high_growth, 0.10)

    transition_growth = (high_growth + 0.03) / 2
    terminal_growth = min(0.03, high_growth * 0.6)

    pv = 0.0
    base_fcf = max(fcf_current, fcf_avg_3yr * 0.85)

    for year in range(1, 4):
        fcf_projected = base_fcf * (1 + high_growth) ** year
        pv += fcf_projected / (1 + wacc) ** year

    for year in range(4, 8):
        transition_rate = transition_growth * (8 - year) / 4
        fcf_projected = (
            base_fcf
            * (1 + high_growth) ** 3
            * (1 + transition_rate) ** (year - 3)
        )
        pv += fcf_projected / (1 + wacc) ** year

    final_fcf = base_fcf * (1 + high_growth) ** 3 * (1 + transition_growth) ** 4
    if wacc <= terminal_growth:
        terminal_growth = wacc * 0.8
    terminal_value = (final_fcf * (1 + terminal_growth)) / (wacc - terminal_growth)
    pv_terminal = terminal_value / (1 + wacc) ** 7

    quality_factor = max(0.7, 1 - (fcf_volatility * 0.5))
    return (pv + pv_terminal) * quality_factor


def calculate_dcf_scenarios(
    fcf_history: list[float],
    growth_metrics: dict,
    wacc: float,
    market_cap: float,
    revenue_growth: float | None = None,
) -> dict[str, Any]:
    """Bear / base / bull scenarios with 20% / 60% / 20% probability weighting."""
    scenarios = {
        "bear": {"growth_adj": 0.5, "wacc_adj": 1.2, "terminal_adj": 0.8},
        "base": {"growth_adj": 1.0, "wacc_adj": 1.0, "terminal_adj": 1.0},
        "bull": {"growth_adj": 1.5, "wacc_adj": 0.9, "terminal_adj": 1.2},
    }

    results: dict[str, float] = {}
    base_revenue_growth = revenue_growth or 0.05

    for scenario, adj in scenarios.items():
        adjusted_rev_growth = base_revenue_growth * adj["growth_adj"]
        adjusted_wacc = wacc * adj["wacc_adj"]
        results[scenario] = calculate_enhanced_dcf_value(
            fcf_history=fcf_history,
            growth_metrics=growth_metrics,
            wacc=adjusted_wacc,
            market_cap=market_cap,
            revenue_growth=adjusted_rev_growth,
        )

    expected_value = (
        results["bear"] * 0.2
        + results["base"] * 0.6
        + results["bull"] * 0.2
    )

    return {
        "scenarios": results,
        "expected_value": expected_value,
        "range": results["bull"] - results["bear"],
        "upside": results["bull"],
        "downside": results["bear"],
    }


# ---------------------------------------------------------------------------
# Top-level aggregator
# ---------------------------------------------------------------------------


def analyze_valuation_combined(
    financial_metrics: list,
    line_items: list,
    market_cap: float | None,
) -> dict[str, Any]:
    """Run all four methodologies, aggregate by weight, and produce a signal.

    Returns {signal, confidence, reasoning} matching the native-layer contract.
    Reasoning contains one entry per method with value/gap/weight plus a
    dcf_scenario_analysis block.
    """
    if not financial_metrics:
        return {
            "signal": "neutral",
            "confidence": 0,
            "reasoning": {"data_warning": "Insufficient data: no financial metrics available"},
        }
    if not line_items or len(line_items) < 2:
        return {
            "signal": "neutral",
            "confidence": 0,
            "reasoning": {"data_warning": "Insufficient data: fewer than 2 periods of line items"},
        }
    if not market_cap or market_cap <= 0:
        return {
            "signal": "neutral",
            "confidence": 0,
            "reasoning": {"data_warning": "Insufficient data: market cap unavailable"},
        }

    most_recent_metrics = financial_metrics[0]
    li_curr = line_items[0]
    li_prev = line_items[1]

    # Working capital change (default to 0 when either period is missing it)
    wc_curr = getattr(li_curr, "working_capital", None)
    wc_prev = getattr(li_prev, "working_capital", None)
    wc_change = (wc_curr - wc_prev) if (wc_curr is not None and wc_prev is not None) else 0

    # --- Owner earnings ---
    owner_val = calculate_owner_earnings_value(
        net_income=getattr(li_curr, "net_income", None),
        depreciation=getattr(li_curr, "depreciation_and_amortization", None),
        capex=getattr(li_curr, "capital_expenditure", None),
        working_capital_change=wc_change,
        growth_rate=getattr(most_recent_metrics, "earnings_growth", None) or 0.05,
    )

    # --- WACC ---
    wacc = calculate_wacc(
        market_cap=market_cap,
        total_debt=getattr(li_curr, "total_debt", None),
        cash=getattr(li_curr, "cash_and_equivalents", None),
        interest_coverage=getattr(most_recent_metrics, "interest_coverage", None),
        debt_to_equity=getattr(most_recent_metrics, "debt_to_equity", None),
    )

    # --- FCF history ---
    fcf_history: list[float] = []
    for li in line_items:
        fcf = getattr(li, "free_cash_flow", None)
        if fcf is not None:
            fcf_history.append(fcf)

    # --- DCF scenarios ---
    dcf_results = calculate_dcf_scenarios(
        fcf_history=fcf_history,
        growth_metrics={
            "revenue_growth": getattr(most_recent_metrics, "revenue_growth", None),
            "fcf_growth": getattr(most_recent_metrics, "free_cash_flow_growth", None),
            "earnings_growth": getattr(most_recent_metrics, "earnings_growth", None),
        },
        wacc=wacc,
        market_cap=market_cap,
        revenue_growth=getattr(most_recent_metrics, "revenue_growth", None),
    )
    dcf_val = dcf_results["expected_value"]

    # --- EV/EBITDA ---
    ev_ebitda_val = calculate_ev_ebitda_value(financial_metrics)

    # --- RIM ---
    rim_val = calculate_residual_income_value(
        market_cap=market_cap,
        net_income=getattr(li_curr, "net_income", None),
        price_to_book_ratio=getattr(most_recent_metrics, "price_to_book_ratio", None),
        book_value_growth=getattr(most_recent_metrics, "book_value_growth", None) or 0.03,
    )

    # --- Aggregate ---
    method_values: dict[str, dict[str, Any]] = {
        "dcf": {"value": dcf_val, "weight": 0.35},
        "owner_earnings": {"value": owner_val, "weight": 0.35},
        "ev_ebitda": {"value": ev_ebitda_val, "weight": 0.20},
        "residual_income": {"value": rim_val, "weight": 0.10},
    }

    total_weight = sum(v["weight"] for v in method_values.values() if v["value"] > 0)
    if total_weight == 0:
        return {
            "signal": "neutral",
            "confidence": 0,
            "reasoning": {
                "data_warning": "Insufficient data: all four valuation methods returned zero",
            },
        }

    for v in method_values.values():
        v["gap"] = (v["value"] - market_cap) / market_cap if v["value"] > 0 else None

    weighted_gap = sum(
        v["weight"] * v["gap"]
        for v in method_values.values()
        if v["gap"] is not None
    ) / total_weight

    if weighted_gap > 0.15:
        signal = "bullish"
    elif weighted_gap < -0.15:
        signal = "bearish"
    else:
        signal = "neutral"

    confidence = round(min(abs(weighted_gap) / 0.30 * 100, 100))

    # --- Reasoning payload ---
    reasoning: dict[str, Any] = {}
    for method, vals in method_values.items():
        if vals["value"] <= 0:
            continue
        base_details = (
            f"Value: ${vals['value']:,.2f}, Market Cap: ${market_cap:,.2f}, "
            f"Gap: {vals['gap']:.1%}, Weight: {vals['weight'] * 100:.0f}%"
        )
        if method == "dcf":
            details = (
                f"{base_details}\n"
                f"  WACC: {wacc:.1%}, Bear: ${dcf_results['downside']:,.2f}, "
                f"Bull: ${dcf_results['upside']:,.2f}, Range: ${dcf_results['range']:,.2f}"
            )
        else:
            details = base_details

        reasoning[f"{method}_analysis"] = {
            "signal": (
                "bullish"
                if vals["gap"] is not None and vals["gap"] > 0.15
                else "bearish"
                if vals["gap"] is not None and vals["gap"] < -0.15
                else "neutral"
            ),
            "details": details,
        }

    reasoning["dcf_scenario_analysis"] = {
        "bear_case": f"${dcf_results['downside']:,.2f}",
        "base_case": f"${dcf_results['scenarios']['base']:,.2f}",
        "bull_case": f"${dcf_results['upside']:,.2f}",
        "wacc_used": f"{wacc:.1%}",
        "fcf_periods_analyzed": len(fcf_history),
    }

    reasoning["weighted_summary"] = {
        "weighted_gap": round(weighted_gap, 4),
        "signal": signal,
        "confidence": confidence,
    }

    return {
        "signal": signal,
        "confidence": confidence,
        "reasoning": reasoning,
    }
