"""Pure analyzer functions for Mohnish Pabrai's investment framework.

Extracted from `mohnish_pabrai.py` so they can be imported without pulling in
LangChain / LangGraph. The original agent module still uses these functions;
the MCP server in `mcp_server/` imports from here directly.
"""
from __future__ import annotations


def analyze_downside_protection(financial_line_items: list) -> dict[str, any]:
    """Assess balance-sheet strength and downside resiliency (capital preservation first)."""
    if not financial_line_items:
        return {"score": 0, "details": "Insufficient data"}

    latest = financial_line_items[0]
    details: list[str] = []
    score = 0

    cash = getattr(latest, "cash_and_equivalents", None)
    debt = getattr(latest, "total_debt", None)
    current_assets = getattr(latest, "current_assets", None)
    current_liabilities = getattr(latest, "current_liabilities", None)
    equity = getattr(latest, "shareholders_equity", None)

    # Net cash position is a strong downside protector
    net_cash = None
    if cash is not None and debt is not None:
        net_cash = cash - debt
        if net_cash > 0:
            score += 3
            details.append(f"Net cash position: ${net_cash:,.0f}")
        else:
            details.append(f"Net debt position: ${net_cash:,.0f}")

    # Current ratio
    if current_assets is not None and current_liabilities is not None and current_liabilities > 0:
        current_ratio = current_assets / current_liabilities
        if current_ratio >= 2.0:
            score += 2
            details.append(f"Strong liquidity (current ratio {current_ratio:.2f})")
        elif current_ratio >= 1.2:
            score += 1
            details.append(f"Adequate liquidity (current ratio {current_ratio:.2f})")
        else:
            details.append(f"Weak liquidity (current ratio {current_ratio:.2f})")

    # Low leverage
    if equity is not None and equity > 0 and debt is not None:
        de_ratio = debt / equity
        if de_ratio < 0.3:
            score += 2
            details.append(f"Very low leverage (D/E {de_ratio:.2f})")
        elif de_ratio < 0.7:
            score += 1
            details.append(f"Moderate leverage (D/E {de_ratio:.2f})")
        else:
            details.append(f"High leverage (D/E {de_ratio:.2f})")

    # Free cash flow positive and stable
    fcf_values = [getattr(li, "free_cash_flow", None) for li in financial_line_items if getattr(li, "free_cash_flow", None) is not None]
    if fcf_values and len(fcf_values) >= 3:
        recent_avg = sum(fcf_values[:3]) / 3
        older = sum(fcf_values[-3:]) / 3 if len(fcf_values) >= 6 else fcf_values[-1]
        if recent_avg > 0 and recent_avg >= older:
            score += 2
            details.append("Positive and improving/stable FCF")
        elif recent_avg > 0:
            score += 1
            details.append("Positive but declining FCF")
        else:
            details.append("Negative FCF")

    return {"score": min(10, score), "details": "; ".join(details)}


def analyze_pabrai_valuation(financial_line_items: list, market_cap: float | None) -> dict[str, any]:
    """Value via simple FCF yield and asset-light preference (keep it simple, low mistakes)."""
    if not financial_line_items or market_cap is None or market_cap <= 0:
        return {"score": 0, "details": "Insufficient data", "fcf_yield": None, "normalized_fcf": None}

    details: list[str] = []
    fcf_values = [getattr(li, "free_cash_flow", None) for li in financial_line_items if getattr(li, "free_cash_flow", None) is not None]
    capex_vals = [abs(getattr(li, "capital_expenditure", 0) or 0) for li in financial_line_items]

    if not fcf_values or len(fcf_values) < 3:
        return {"score": 0, "details": "Insufficient FCF history", "fcf_yield": None, "normalized_fcf": None}

    normalized_fcf = sum(fcf_values[:min(5, len(fcf_values))]) / min(5, len(fcf_values))
    if normalized_fcf <= 0:
        return {"score": 0, "details": "Non-positive normalized FCF", "fcf_yield": None, "normalized_fcf": normalized_fcf}

    fcf_yield = normalized_fcf / market_cap

    score = 0
    if fcf_yield > 0.10:
        score += 4
        details.append(f"Exceptional value: {fcf_yield:.1%} FCF yield")
    elif fcf_yield > 0.07:
        score += 3
        details.append(f"Attractive value: {fcf_yield:.1%} FCF yield")
    elif fcf_yield > 0.05:
        score += 2
        details.append(f"Reasonable value: {fcf_yield:.1%} FCF yield")
    elif fcf_yield > 0.03:
        score += 1
        details.append(f"Borderline value: {fcf_yield:.1%} FCF yield")
    else:
        details.append(f"Expensive: {fcf_yield:.1%} FCF yield")

    # Asset-light tilt: lower capex intensity preferred
    if capex_vals and len(financial_line_items) >= 3:
        revenue_vals = [getattr(li, "revenue", None) for li in financial_line_items]
        capex_to_revenue = []
        for i, li in enumerate(financial_line_items):
            revenue = getattr(li, "revenue", None)
            capex = abs(getattr(li, "capital_expenditure", 0) or 0)
            if revenue and revenue > 0:
                capex_to_revenue.append(capex / revenue)
        if capex_to_revenue:
            avg_ratio = sum(capex_to_revenue) / len(capex_to_revenue)
            if avg_ratio < 0.05:
                score += 2
                details.append(f"Asset-light: Avg capex {avg_ratio:.1%} of revenue")
            elif avg_ratio < 0.10:
                score += 1
                details.append(f"Moderate capex: Avg capex {avg_ratio:.1%} of revenue")
            else:
                details.append(f"Capex heavy: Avg capex {avg_ratio:.1%} of revenue")

    return {"score": min(10, score), "details": "; ".join(details), "fcf_yield": fcf_yield, "normalized_fcf": normalized_fcf}


def analyze_double_potential(financial_line_items: list, market_cap: float | None) -> dict[str, any]:
    """Estimate low-risk path to double capital in ~2-3 years: runway from FCF growth + rerating."""
    if not financial_line_items or market_cap is None or market_cap <= 0:
        return {"score": 0, "details": "Insufficient data"}

    details: list[str] = []

    # Use revenue and FCF trends as rough growth proxy (keep it simple)
    revenues = [getattr(li, "revenue", None) for li in financial_line_items if getattr(li, "revenue", None) is not None]
    fcfs = [getattr(li, "free_cash_flow", None) for li in financial_line_items if getattr(li, "free_cash_flow", None) is not None]

    score = 0
    if revenues and len(revenues) >= 3:
        recent_rev = sum(revenues[:3]) / 3
        older_rev = sum(revenues[-3:]) / 3 if len(revenues) >= 6 else revenues[-1]
        if older_rev > 0:
            rev_growth = (recent_rev / older_rev) - 1
            if rev_growth > 0.15:
                score += 2
                details.append(f"Strong revenue trajectory ({rev_growth:.1%})")
            elif rev_growth > 0.05:
                score += 1
                details.append(f"Modest revenue growth ({rev_growth:.1%})")

    if fcfs and len(fcfs) >= 3:
        recent_fcf = sum(fcfs[:3]) / 3
        older_fcf = sum(fcfs[-3:]) / 3 if len(fcfs) >= 6 else fcfs[-1]
        if older_fcf != 0:
            fcf_growth = (recent_fcf / older_fcf) - 1
            if fcf_growth > 0.20:
                score += 3
                details.append(f"Strong FCF growth ({fcf_growth:.1%})")
            elif fcf_growth > 0.08:
                score += 2
                details.append(f"Healthy FCF growth ({fcf_growth:.1%})")
            elif fcf_growth > 0:
                score += 1
                details.append(f"Positive FCF growth ({fcf_growth:.1%})")

    # If FCF yield is already high (>8%), doubling can come from cash generation alone in few years
    tmp_val = analyze_pabrai_valuation(financial_line_items, market_cap)
    fcf_yield = tmp_val.get("fcf_yield")
    if fcf_yield is not None:
        if fcf_yield > 0.08:
            score += 3
            details.append("High FCF yield can drive doubling via retained cash/Buybacks")
        elif fcf_yield > 0.05:
            score += 1
            details.append("Reasonable FCF yield supports moderate compounding")

    return {"score": min(10, score), "details": "; ".join(details)}
