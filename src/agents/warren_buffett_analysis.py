"""Pure analyzer functions for Warren Buffett's investment framework.

Extracted from `warren_buffett.py` so they can be imported without pulling in
LangChain / LangGraph. The original agent module re-exports these, so nothing
downstream breaks. The MCP server in `mcp_server/` imports from here directly.
"""
from __future__ import annotations


def analyze_fundamentals(metrics: list) -> dict[str, any]:
    """Analyze company fundamentals based on Buffett's criteria."""
    if not metrics:
        return {"score": 0, "details": "Insufficient fundamental data"}

    latest_metrics = metrics[0]

    score = 0
    reasoning = []

    # ROE
    if latest_metrics.return_on_equity and latest_metrics.return_on_equity > 0.15:
        score += 2
        reasoning.append(f"Strong ROE of {latest_metrics.return_on_equity:.1%}")
    elif latest_metrics.return_on_equity:
        reasoning.append(f"Weak ROE of {latest_metrics.return_on_equity:.1%}")
    else:
        reasoning.append("ROE data not available")

    # Debt / equity
    if latest_metrics.debt_to_equity and latest_metrics.debt_to_equity < 0.5:
        score += 2
        reasoning.append("Conservative debt levels")
    elif latest_metrics.debt_to_equity:
        reasoning.append(f"High debt to equity ratio of {latest_metrics.debt_to_equity:.1f}")
    else:
        reasoning.append("Debt to equity data not available")

    # Operating margin
    if latest_metrics.operating_margin and latest_metrics.operating_margin > 0.15:
        score += 2
        reasoning.append("Strong operating margins")
    elif latest_metrics.operating_margin:
        reasoning.append(f"Weak operating margin of {latest_metrics.operating_margin:.1%}")
    else:
        reasoning.append("Operating margin data not available")

    # Current ratio
    if latest_metrics.current_ratio and latest_metrics.current_ratio > 1.5:
        score += 1
        reasoning.append("Good liquidity position")
    elif latest_metrics.current_ratio:
        reasoning.append(f"Weak liquidity with current ratio of {latest_metrics.current_ratio:.1f}")
    else:
        reasoning.append("Current ratio data not available")

    return {"score": score, "details": "; ".join(reasoning), "metrics": latest_metrics.model_dump()}


def analyze_consistency(financial_line_items: list) -> dict[str, any]:
    """Analyze earnings consistency and growth."""
    if len(financial_line_items) < 4:
        return {"score": 0, "details": "Insufficient historical data"}

    score = 0
    reasoning = []

    earnings_values = [item.net_income for item in financial_line_items if item.net_income]
    if len(earnings_values) >= 4:
        earnings_growth = all(earnings_values[i] > earnings_values[i + 1] for i in range(len(earnings_values) - 1))

        if earnings_growth:
            score += 3
            reasoning.append("Consistent earnings growth over past periods")
        else:
            reasoning.append("Inconsistent earnings growth pattern")

        if len(earnings_values) >= 2 and earnings_values[-1] != 0:
            growth_rate = (earnings_values[0] - earnings_values[-1]) / abs(earnings_values[-1])
            reasoning.append(f"Total earnings growth of {growth_rate:.1%} over past {len(earnings_values)} periods")
    else:
        reasoning.append("Insufficient earnings data for trend analysis")

    return {"score": score, "details": "; ".join(reasoning)}


def analyze_moat(metrics: list) -> dict[str, any]:
    """Evaluate whether the company likely has a durable competitive advantage."""
    if not metrics or len(metrics) < 5:
        return {"score": 0, "max_score": 5, "details": "Insufficient data for comprehensive moat analysis"}

    reasoning = []
    moat_score = 0
    max_score = 5

    historical_roes = [m.return_on_equity for m in metrics if m.return_on_equity is not None]
    historical_roics = [m.return_on_invested_capital for m in metrics
                        if hasattr(m, 'return_on_invested_capital') and m.return_on_invested_capital is not None]

    if len(historical_roes) >= 5:
        high_roe_periods = sum(1 for roe in historical_roes if roe > 0.15)
        roe_consistency = high_roe_periods / len(historical_roes)

        if roe_consistency >= 0.8:
            moat_score += 2
            avg_roe = sum(historical_roes) / len(historical_roes)
            reasoning.append(
                f"Excellent ROE consistency: {high_roe_periods}/{len(historical_roes)} periods >15% (avg: {avg_roe:.1%}) - indicates durable competitive advantage"
            )
        elif roe_consistency >= 0.6:
            moat_score += 1
            reasoning.append(f"Good ROE performance: {high_roe_periods}/{len(historical_roes)} periods >15%")
        else:
            reasoning.append(f"Inconsistent ROE: only {high_roe_periods}/{len(historical_roes)} periods >15%")
    else:
        reasoning.append("Insufficient ROE history for moat analysis")

    historical_margins = [m.operating_margin for m in metrics if m.operating_margin is not None]
    if len(historical_margins) >= 5:
        avg_margin = sum(historical_margins) / len(historical_margins)
        recent_margins = historical_margins[:3]
        older_margins = historical_margins[-3:]
        recent_avg = sum(recent_margins) / len(recent_margins)
        older_avg = sum(older_margins) / len(older_margins)

        if avg_margin > 0.2 and recent_avg >= older_avg:
            moat_score += 1
            reasoning.append(f"Strong and stable operating margins (avg: {avg_margin:.1%}) indicate pricing power moat")
        elif avg_margin > 0.15:
            reasoning.append(f"Decent operating margins (avg: {avg_margin:.1%}) suggest some competitive advantage")
        else:
            reasoning.append(f"Low operating margins (avg: {avg_margin:.1%}) suggest limited pricing power")

    if len(metrics) >= 5:
        asset_turnovers = [m.asset_turnover for m in metrics
                           if hasattr(m, 'asset_turnover') and m.asset_turnover is not None]
        if len(asset_turnovers) >= 3:
            if any(turnover > 1.0 for turnover in asset_turnovers):
                moat_score += 1
                reasoning.append("Efficient asset utilization suggests operational moat")

    if len(historical_roes) >= 5 and len(historical_margins) >= 5:
        roe_avg = sum(historical_roes) / len(historical_roes)
        roe_variance = sum((roe - roe_avg) ** 2 for roe in historical_roes) / len(historical_roes)
        roe_stability = 1 - (roe_variance ** 0.5) / roe_avg if roe_avg > 0 else 0

        margin_avg = sum(historical_margins) / len(historical_margins)
        margin_variance = sum((margin - margin_avg) ** 2 for margin in historical_margins) / len(historical_margins)
        margin_stability = 1 - (margin_variance ** 0.5) / margin_avg if margin_avg > 0 else 0

        overall_stability = (roe_stability + margin_stability) / 2

        if overall_stability > 0.7:
            moat_score += 1
            reasoning.append(f"High performance stability ({overall_stability:.1%}) suggests strong competitive moat")

    moat_score = min(moat_score, max_score)

    return {
        "score": moat_score,
        "max_score": max_score,
        "details": "; ".join(reasoning) if reasoning else "Limited moat analysis available",
    }


def analyze_management_quality(financial_line_items: list) -> dict[str, any]:
    """Check share dilution or buybacks and dividend track record."""
    if not financial_line_items:
        return {"score": 0, "max_score": 2, "details": "Insufficient data for management analysis"}

    reasoning = []
    mgmt_score = 0

    latest = financial_line_items[0]
    if (hasattr(latest, "issuance_or_purchase_of_equity_shares")
            and latest.issuance_or_purchase_of_equity_shares
            and latest.issuance_or_purchase_of_equity_shares < 0):
        mgmt_score += 1
        reasoning.append("Company has been repurchasing shares (shareholder-friendly)")

    if (hasattr(latest, "issuance_or_purchase_of_equity_shares")
            and latest.issuance_or_purchase_of_equity_shares
            and latest.issuance_or_purchase_of_equity_shares > 0):
        reasoning.append("Recent common stock issuance (potential dilution)")
    else:
        reasoning.append("No significant new stock issuance detected")

    if (hasattr(latest, "dividends_and_other_cash_distributions")
            and latest.dividends_and_other_cash_distributions
            and latest.dividends_and_other_cash_distributions < 0):
        mgmt_score += 1
        reasoning.append("Company has a track record of paying dividends")
    else:
        reasoning.append("No or minimal dividends paid")

    return {"score": mgmt_score, "max_score": 2, "details": "; ".join(reasoning)}


def estimate_maintenance_capex(financial_line_items: list) -> float:
    """Estimate maintenance capex via median of three approaches."""
    if not financial_line_items:
        return 0

    capex_ratios = []
    depreciation_values = []

    for item in financial_line_items[:5]:
        if hasattr(item, 'capital_expenditure') and hasattr(item, 'revenue'):
            if item.capital_expenditure and item.revenue and item.revenue > 0:
                capex_ratios.append(abs(item.capital_expenditure) / item.revenue)
        if hasattr(item, 'depreciation_and_amortization') and item.depreciation_and_amortization:
            depreciation_values.append(item.depreciation_and_amortization)

    latest_depreciation = financial_line_items[0].depreciation_and_amortization if financial_line_items[0].depreciation_and_amortization else 0
    latest_capex = abs(financial_line_items[0].capital_expenditure) if financial_line_items[0].capital_expenditure else 0

    method_1 = latest_capex * 0.85
    method_2 = latest_depreciation

    if len(capex_ratios) >= 3:
        avg_capex_ratio = sum(capex_ratios) / len(capex_ratios)
        latest_revenue = financial_line_items[0].revenue if hasattr(financial_line_items[0], 'revenue') and financial_line_items[0].revenue else 0
        method_3 = avg_capex_ratio * latest_revenue if latest_revenue else 0
        return sorted([method_1, method_2, method_3])[1]
    return max(method_1, method_2)


def calculate_owner_earnings(financial_line_items: list) -> dict[str, any]:
    """Buffett's owner earnings: NI + D&A − maintenance capex − ΔWC."""
    if not financial_line_items or len(financial_line_items) < 2:
        return {"owner_earnings": None, "details": ["Insufficient data for owner earnings calculation"]}

    latest = financial_line_items[0]
    details = []

    net_income = latest.net_income
    depreciation = latest.depreciation_and_amortization
    capex = latest.capital_expenditure

    if not all([net_income is not None, depreciation is not None, capex is not None]):
        missing = []
        if net_income is None:
            missing.append("net income")
        if depreciation is None:
            missing.append("depreciation")
        if capex is None:
            missing.append("capital expenditure")
        return {"owner_earnings": None, "details": [f"Missing components: {', '.join(missing)}"]}

    maintenance_capex = estimate_maintenance_capex(financial_line_items)

    working_capital_change = 0
    if len(financial_line_items) >= 2:
        try:
            current_assets_current = getattr(latest, 'current_assets', None)
            current_liab_current = getattr(latest, 'current_liabilities', None)
            previous = financial_line_items[1]
            current_assets_previous = getattr(previous, 'current_assets', None)
            current_liab_previous = getattr(previous, 'current_liabilities', None)

            if all([current_assets_current, current_liab_current, current_assets_previous, current_liab_previous]):
                wc_current = current_assets_current - current_liab_current
                wc_previous = current_assets_previous - current_liab_previous
                working_capital_change = wc_current - wc_previous
                details.append(f"Working capital change: ${working_capital_change:,.0f}")
        except Exception:
            pass

    owner_earnings = net_income + depreciation - maintenance_capex - working_capital_change

    if owner_earnings < net_income * 0.3:
        details.append("Warning: Owner earnings significantly below net income - high capex intensity")
    if maintenance_capex > depreciation * 2:
        details.append("Warning: Estimated maintenance capex seems high relative to depreciation")

    details.extend([
        f"Net income: ${net_income:,.0f}",
        f"Depreciation: ${depreciation:,.0f}",
        f"Estimated maintenance capex: ${maintenance_capex:,.0f}",
        f"Owner earnings: ${owner_earnings:,.0f}",
    ])

    return {
        "owner_earnings": owner_earnings,
        "components": {
            "net_income": net_income,
            "depreciation": depreciation,
            "maintenance_capex": maintenance_capex,
            "working_capital_change": working_capital_change,
            "total_capex": abs(capex) if capex else 0,
        },
        "details": details,
    }


def calculate_intrinsic_value(financial_line_items: list) -> dict[str, any]:
    """Three-stage DCF on owner earnings with 15% safety haircut."""
    if not financial_line_items or len(financial_line_items) < 3:
        return {"intrinsic_value": None, "details": ["Insufficient data for reliable valuation"]}

    earnings_data = calculate_owner_earnings(financial_line_items)
    if not earnings_data["owner_earnings"]:
        return {"intrinsic_value": None, "details": earnings_data["details"]}

    owner_earnings = earnings_data["owner_earnings"]
    latest = financial_line_items[0]
    shares_outstanding = latest.outstanding_shares

    if not shares_outstanding or shares_outstanding <= 0:
        return {"intrinsic_value": None, "details": ["Missing or invalid shares outstanding data"]}

    details = []

    historical_earnings = [item.net_income for item in financial_line_items[:5]
                           if hasattr(item, 'net_income') and item.net_income]

    if len(historical_earnings) >= 3:
        oldest_earnings = historical_earnings[-1]
        latest_earnings = historical_earnings[0]
        years = len(historical_earnings) - 1
        if oldest_earnings > 0:
            historical_growth = ((latest_earnings / oldest_earnings) ** (1 / years)) - 1
            historical_growth = max(-0.05, min(historical_growth, 0.15))
            conservative_growth = historical_growth * 0.7
        else:
            conservative_growth = 0.03
    else:
        conservative_growth = 0.03

    stage1_growth = min(conservative_growth, 0.08)
    stage2_growth = min(conservative_growth * 0.5, 0.04)
    terminal_growth = 0.025
    discount_rate = 0.10
    stage1_years = 5
    stage2_years = 5

    details.append(
        f"Using three-stage DCF: Stage 1 ({stage1_growth:.1%}, {stage1_years}y), Stage 2 ({stage2_growth:.1%}, {stage2_years}y), Terminal ({terminal_growth:.1%})"
    )

    stage1_pv = 0
    for year in range(1, stage1_years + 1):
        future = owner_earnings * (1 + stage1_growth) ** year
        stage1_pv += future / (1 + discount_rate) ** year

    stage2_pv = 0
    stage1_final = owner_earnings * (1 + stage1_growth) ** stage1_years
    for year in range(1, stage2_years + 1):
        future = stage1_final * (1 + stage2_growth) ** year
        stage2_pv += future / (1 + discount_rate) ** (stage1_years + year)

    final_earnings = stage1_final * (1 + stage2_growth) ** stage2_years
    terminal_earnings = final_earnings * (1 + terminal_growth)
    terminal_value = terminal_earnings / (discount_rate - terminal_growth)
    terminal_pv = terminal_value / (1 + discount_rate) ** (stage1_years + stage2_years)

    intrinsic_value = stage1_pv + stage2_pv + terminal_pv
    conservative_intrinsic_value = intrinsic_value * 0.85

    details.extend([
        f"Stage 1 PV: ${stage1_pv:,.0f}",
        f"Stage 2 PV: ${stage2_pv:,.0f}",
        f"Terminal PV: ${terminal_pv:,.0f}",
        f"Total IV: ${intrinsic_value:,.0f}",
        f"Conservative IV (15% haircut): ${conservative_intrinsic_value:,.0f}",
        f"Owner earnings: ${owner_earnings:,.0f}",
        f"Discount rate: {discount_rate:.1%}",
    ])

    return {
        "intrinsic_value": conservative_intrinsic_value,
        "raw_intrinsic_value": intrinsic_value,
        "owner_earnings": owner_earnings,
        "assumptions": {
            "stage1_growth": stage1_growth,
            "stage2_growth": stage2_growth,
            "terminal_growth": terminal_growth,
            "discount_rate": discount_rate,
            "stage1_years": stage1_years,
            "stage2_years": stage2_years,
            "historical_growth": conservative_growth,
        },
        "details": details,
    }


def _calculate_book_value_cagr(book_values: list) -> tuple[int, str]:
    """Score + reason for book value CAGR, handling sign changes safely."""
    if len(book_values) < 2:
        return 0, "Insufficient data for CAGR calculation"

    oldest_bv, latest_bv = book_values[-1], book_values[0]
    years = len(book_values) - 1

    if oldest_bv > 0 and latest_bv > 0:
        cagr = ((latest_bv / oldest_bv) ** (1 / years)) - 1
        if cagr > 0.15:
            return 2, f"Excellent book value CAGR: {cagr:.1%}"
        if cagr > 0.1:
            return 1, f"Good book value CAGR: {cagr:.1%}"
        return 0, f"Book value CAGR: {cagr:.1%}"
    if oldest_bv < 0 < latest_bv:
        return 3, "Excellent: Company improved from negative to positive book value"
    if oldest_bv > 0 > latest_bv:
        return 0, "Warning: Company declined from positive to negative book value"
    return 0, "Unable to calculate meaningful book value CAGR due to negative values"


def analyze_book_value_growth(financial_line_items: list) -> dict[str, any]:
    """Book value per share growth — a key Buffett metric."""
    if len(financial_line_items) < 3:
        return {"score": 0, "details": "Insufficient data for book value analysis"}

    book_values = [
        item.shareholders_equity / item.outstanding_shares
        for item in financial_line_items
        if hasattr(item, 'shareholders_equity') and hasattr(item, 'outstanding_shares')
        and item.shareholders_equity and item.outstanding_shares
    ]
    if len(book_values) < 3:
        return {"score": 0, "details": "Insufficient book value data for growth analysis"}

    score = 0
    reasoning = []

    growth_periods = sum(1 for i in range(len(book_values) - 1) if book_values[i] > book_values[i + 1])
    growth_rate = growth_periods / (len(book_values) - 1)

    if growth_rate >= 0.8:
        score += 3
        reasoning.append("Consistent book value per share growth (Buffett's favorite metric)")
    elif growth_rate >= 0.6:
        score += 2
        reasoning.append("Good book value per share growth pattern")
    elif growth_rate >= 0.4:
        score += 1
        reasoning.append("Moderate book value per share growth")
    else:
        reasoning.append("Inconsistent book value per share growth")

    cagr_score, cagr_reason = _calculate_book_value_cagr(book_values)
    score += cagr_score
    reasoning.append(cagr_reason)

    return {"score": score, "details": "; ".join(reasoning)}


def analyze_pricing_power(financial_line_items: list, metrics: list) -> dict[str, any]:
    """Gross margin trends as a proxy for pricing power."""
    if not financial_line_items or not metrics:
        return {"score": 0, "details": "Insufficient data for pricing power analysis"}

    score = 0
    reasoning = []

    gross_margins = [item.gross_margin for item in financial_line_items
                     if hasattr(item, 'gross_margin') and item.gross_margin is not None]

    if len(gross_margins) >= 3:
        recent_avg = sum(gross_margins[:2]) / 2 if len(gross_margins) >= 2 else gross_margins[0]
        older_avg = sum(gross_margins[-2:]) / 2 if len(gross_margins) >= 2 else gross_margins[-1]

        if recent_avg > older_avg + 0.02:
            score += 3
            reasoning.append("Expanding gross margins indicate strong pricing power")
        elif recent_avg > older_avg:
            score += 2
            reasoning.append("Improving gross margins suggest good pricing power")
        elif abs(recent_avg - older_avg) < 0.01:
            score += 1
            reasoning.append("Stable gross margins during economic uncertainty")
        else:
            reasoning.append("Declining gross margins may indicate pricing pressure")

    if gross_margins:
        avg_margin = sum(gross_margins) / len(gross_margins)
        if avg_margin > 0.5:
            score += 2
            reasoning.append(f"Consistently high gross margins ({avg_margin:.1%}) indicate strong pricing power")
        elif avg_margin > 0.3:
            score += 1
            reasoning.append(f"Good gross margins ({avg_margin:.1%}) suggest decent pricing power")

    return {"score": score, "details": "; ".join(reasoning) if reasoning else "Limited pricing power analysis available"}
