"""Pure analyzer functions for Rakesh Jhunjhunwala's investment framework.

Extracted from `rakesh_jhunjhunwala.py` so they can be imported without pulling
in LangChain / LangGraph. The original agent module still contains the LLM
orchestration glue; these pure functions are shared between the v1 LangGraph
flow and the Claude Code native MCP server.
"""
from __future__ import annotations


def analyze_profitability(financial_line_items: list) -> dict[str, any]:
    """
    Analyze profitability metrics like net income, EBIT, EPS, operating income.
    Focus on strong, consistent earnings growth and operating efficiency.
    """
    if not financial_line_items:
        return {"score": 0, "details": "No profitability data available"}

    latest = financial_line_items[0]
    score = 0
    reasoning = []

    # Calculate ROE (Return on Equity) - Jhunjhunwala's key metric
    if (getattr(latest, 'net_income', None) and latest.net_income > 0 and
        getattr(latest, 'total_assets', None) and getattr(latest, 'total_liabilities', None) and
        latest.total_assets and latest.total_liabilities):

        shareholders_equity = latest.total_assets - latest.total_liabilities
        if shareholders_equity > 0:
            roe = (latest.net_income / shareholders_equity) * 100
            if roe > 20:  # Excellent ROE
                score += 3
                reasoning.append(f"Excellent ROE: {roe:.1f}%")
            elif roe > 15:  # Good ROE
                score += 2
                reasoning.append(f"Good ROE: {roe:.1f}%")
            elif roe > 10:  # Decent ROE
                score += 1
                reasoning.append(f"Decent ROE: {roe:.1f}%")
            else:
                reasoning.append(f"Low ROE: {roe:.1f}%")
        else:
            reasoning.append("Negative shareholders equity")
    else:
        reasoning.append("Unable to calculate ROE - missing data")

    # Operating Margin Analysis
    if (getattr(latest, "operating_income", None) and latest.operating_income and
        getattr(latest, "revenue", None) and latest.revenue and latest.revenue > 0):
        operating_margin = (latest.operating_income / latest.revenue) * 100
        if operating_margin > 20:  # Excellent margin
            score += 2
            reasoning.append(f"Excellent operating margin: {operating_margin:.1f}%")
        elif operating_margin > 15:  # Good margin
            score += 1
            reasoning.append(f"Good operating margin: {operating_margin:.1f}%")
        elif operating_margin > 0:
            reasoning.append(f"Positive operating margin: {operating_margin:.1f}%")
        else:
            reasoning.append(f"Negative operating margin: {operating_margin:.1f}%")
    else:
        reasoning.append("Unable to calculate operating margin")

    # EPS Growth Consistency (3-year trend)
    eps_values = [getattr(item, "earnings_per_share", None) for item in financial_line_items
                  if getattr(item, "earnings_per_share", None) is not None and getattr(item, "earnings_per_share", None) > 0]

    if len(eps_values) >= 3:
        # Calculate CAGR for EPS
        initial_eps = eps_values[-1]  # Oldest value
        final_eps = eps_values[0]     # Latest value
        years = len(eps_values) - 1

        if initial_eps > 0:
            eps_cagr = ((final_eps / initial_eps) ** (1/years) - 1) * 100
            if eps_cagr > 20:  # High growth
                score += 3
                reasoning.append(f"High EPS CAGR: {eps_cagr:.1f}%")
            elif eps_cagr > 15:  # Good growth
                score += 2
                reasoning.append(f"Good EPS CAGR: {eps_cagr:.1f}%")
            elif eps_cagr > 10:  # Moderate growth
                score += 1
                reasoning.append(f"Moderate EPS CAGR: {eps_cagr:.1f}%")
            else:
                reasoning.append(f"Low EPS CAGR: {eps_cagr:.1f}%")
        else:
            reasoning.append("Cannot calculate EPS growth from negative base")
    else:
        reasoning.append("Insufficient EPS data for growth analysis")

    return {"score": score, "details": "; ".join(reasoning)}


def analyze_growth(financial_line_items: list) -> dict[str, any]:
    """
    Analyze revenue and net income growth trends using CAGR.
    Jhunjhunwala favored companies with strong, consistent compound growth.
    """
    if len(financial_line_items) < 3:
        return {"score": 0, "details": "Insufficient data for growth analysis"}

    score = 0
    reasoning = []

    # Revenue CAGR Analysis
    revenues = [getattr(item, "revenue", None) for item in financial_line_items
                if getattr(item, "revenue", None) is not None and getattr(item, "revenue", None) > 0]

    if len(revenues) >= 3:
        initial_revenue = revenues[-1]  # Oldest
        final_revenue = revenues[0]     # Latest
        years = len(revenues) - 1

        if initial_revenue > 0:  # Fixed: Add zero check
            revenue_cagr = ((final_revenue / initial_revenue) ** (1/years) - 1) * 100

            if revenue_cagr > 20:  # High growth
                score += 3
                reasoning.append(f"Excellent revenue CAGR: {revenue_cagr:.1f}%")
            elif revenue_cagr > 15:  # Good growth
                score += 2
                reasoning.append(f"Good revenue CAGR: {revenue_cagr:.1f}%")
            elif revenue_cagr > 10:  # Moderate growth
                score += 1
                reasoning.append(f"Moderate revenue CAGR: {revenue_cagr:.1f}%")
            else:
                reasoning.append(f"Low revenue CAGR: {revenue_cagr:.1f}%")
        else:
            reasoning.append("Cannot calculate revenue CAGR from zero base")
    else:
        reasoning.append("Insufficient revenue data for CAGR calculation")

    # Net Income CAGR Analysis
    net_incomes = [getattr(item, "net_income", None) for item in financial_line_items
                   if getattr(item, "net_income", None) is not None and getattr(item, "net_income", None) > 0]

    if len(net_incomes) >= 3:
        initial_income = net_incomes[-1]  # Oldest
        final_income = net_incomes[0]     # Latest
        years = len(net_incomes) - 1

        if initial_income > 0:  # Fixed: Add zero check
            income_cagr = ((final_income / initial_income) ** (1/years) - 1) * 100

            if income_cagr > 25:  # Very high growth
                score += 3
                reasoning.append(f"Excellent income CAGR: {income_cagr:.1f}%")
            elif income_cagr > 20:  # High growth
                score += 2
                reasoning.append(f"High income CAGR: {income_cagr:.1f}%")
            elif income_cagr > 15:  # Good growth
                score += 1
                reasoning.append(f"Good income CAGR: {income_cagr:.1f}%")
            else:
                reasoning.append(f"Moderate income CAGR: {income_cagr:.1f}%")
        else:
            reasoning.append("Cannot calculate income CAGR from zero base")
    else:
        reasoning.append("Insufficient net income data for CAGR calculation")

    # Revenue Consistency Check (year-over-year)
    if len(revenues) >= 3:
        declining_years = sum(1 for i in range(1, len(revenues)) if revenues[i-1] > revenues[i])
        consistency_ratio = 1 - (declining_years / (len(revenues) - 1))

        if consistency_ratio >= 0.8:  # 80% or more years with growth
            score += 1
            reasoning.append(f"Consistent growth pattern ({consistency_ratio*100:.0f}% of years)")
        else:
            reasoning.append(f"Inconsistent growth pattern ({consistency_ratio*100:.0f}% of years)")

    return {"score": score, "details": "; ".join(reasoning)}


def analyze_balance_sheet(financial_line_items: list) -> dict[str, any]:
    """
    Check financial strength - healthy asset/liability structure, liquidity.
    Jhunjhunwala favored companies with clean balance sheets and manageable debt.
    """
    if not financial_line_items:
        return {"score": 0, "details": "No balance sheet data"}

    latest = financial_line_items[0]
    score = 0
    reasoning = []

    # Debt to asset ratio
    if (getattr(latest, "total_assets", None) and getattr(latest, "total_liabilities", None)
        and latest.total_assets and latest.total_liabilities
        and latest.total_assets > 0):
        debt_ratio = latest.total_liabilities / latest.total_assets
        if debt_ratio < 0.5:
            score += 2
            reasoning.append(f"Low debt ratio: {debt_ratio:.2f}")
        elif debt_ratio < 0.7:
            score += 1
            reasoning.append(f"Moderate debt ratio: {debt_ratio:.2f}")
        else:
            reasoning.append(f"High debt ratio: {debt_ratio:.2f}")
    else:
        reasoning.append("Insufficient data to calculate debt ratio")

    # Current ratio (liquidity)
    if (getattr(latest, "current_assets", None) and getattr(latest, "current_liabilities", None)
        and latest.current_assets and latest.current_liabilities
        and latest.current_liabilities > 0):
        current_ratio = latest.current_assets / latest.current_liabilities
        if current_ratio > 2.0:
            score += 2
            reasoning.append(f"Excellent liquidity with current ratio: {current_ratio:.2f}")
        elif current_ratio > 1.5:
            score += 1
            reasoning.append(f"Good liquidity with current ratio: {current_ratio:.2f}")
        else:
            reasoning.append(f"Weak liquidity with current ratio: {current_ratio:.2f}")
    else:
        reasoning.append("Insufficient data to calculate current ratio")

    return {"score": score, "details": "; ".join(reasoning)}


def analyze_cash_flow(financial_line_items: list) -> dict[str, any]:
    """
    Evaluate free cash flow and dividend behavior.
    Jhunjhunwala appreciated companies generating strong free cash flow and rewarding shareholders.
    """
    if not financial_line_items:
        return {"score": 0, "details": "No cash flow data"}

    latest = financial_line_items[0]
    score = 0
    reasoning = []

    # Free cash flow analysis
    if getattr(latest, "free_cash_flow", None) and latest.free_cash_flow:
        if latest.free_cash_flow > 0:
            score += 2
            reasoning.append(f"Positive free cash flow: {latest.free_cash_flow}")
        else:
            reasoning.append(f"Negative free cash flow: {latest.free_cash_flow}")
    else:
        reasoning.append("Free cash flow data not available")

    # Dividend analysis
    if getattr(latest, "dividends_and_other_cash_distributions", None) and latest.dividends_and_other_cash_distributions:
        if latest.dividends_and_other_cash_distributions < 0:  # Negative indicates cash outflow for dividends
            score += 1
            reasoning.append("Company pays dividends to shareholders")
        else:
            reasoning.append("No significant dividend payments")
    else:
        reasoning.append("No dividend payment data available")

    return {"score": score, "details": "; ".join(reasoning)}


def analyze_management_actions(financial_line_items: list) -> dict[str, any]:
    """
    Look at share issuance or buybacks to assess shareholder friendliness.
    Jhunjhunwala liked managements who buy back shares or avoid dilution.
    """
    if not financial_line_items:
        return {"score": 0, "details": "No management action data"}

    latest = financial_line_items[0]
    score = 0
    reasoning = []

    issuance = getattr(latest, "issuance_or_purchase_of_equity_shares", None)
    if issuance is not None:
        if issuance < 0:  # Negative indicates share buybacks
            score += 2
            reasoning.append(f"Company buying back shares: {abs(issuance)}")
        elif issuance > 0:
            reasoning.append(f"Share issuance detected (potential dilution): {issuance}")
        else:
            score += 1
            reasoning.append("No recent share issuance or buyback")
    else:
        reasoning.append("No data on share issuance or buybacks")

    return {"score": score, "details": "; ".join(reasoning)}


def assess_quality_metrics(financial_line_items: list) -> float:
    """
    Assess company quality based on Jhunjhunwala's criteria.
    Returns a score between 0 and 1.
    """
    if not financial_line_items:
        return 0.5  # Neutral score

    latest = financial_line_items[0]
    quality_factors = []

    # ROE consistency and level
    if (getattr(latest, 'net_income', None) and getattr(latest, 'total_assets', None) and
        getattr(latest, 'total_liabilities', None) and latest.total_assets and latest.total_liabilities):

        shareholders_equity = latest.total_assets - latest.total_liabilities
        if shareholders_equity > 0 and latest.net_income:
            roe = latest.net_income / shareholders_equity
            if roe > 0.20:  # ROE > 20%
                quality_factors.append(1.0)
            elif roe > 0.15:  # ROE > 15%
                quality_factors.append(0.8)
            elif roe > 0.10:  # ROE > 10%
                quality_factors.append(0.6)
            else:
                quality_factors.append(0.3)
        else:
            quality_factors.append(0.0)
    else:
        quality_factors.append(0.5)

    # Debt levels (lower is better)
    if (getattr(latest, 'total_assets', None) and getattr(latest, 'total_liabilities', None) and
        latest.total_assets and latest.total_liabilities):
        debt_ratio = latest.total_liabilities / latest.total_assets
        if debt_ratio < 0.3:  # Low debt
            quality_factors.append(1.0)
        elif debt_ratio < 0.5:  # Moderate debt
            quality_factors.append(0.7)
        elif debt_ratio < 0.7:  # High debt
            quality_factors.append(0.4)
        else:  # Very high debt
            quality_factors.append(0.1)
    else:
        quality_factors.append(0.5)

    # Growth consistency
    net_incomes = [getattr(item, "net_income", None) for item in financial_line_items[:4]
                   if getattr(item, "net_income", None) is not None and getattr(item, "net_income", None) > 0]

    if len(net_incomes) >= 3:
        declining_years = sum(1 for i in range(1, len(net_incomes)) if net_incomes[i-1] > net_incomes[i])
        consistency = 1 - (declining_years / (len(net_incomes) - 1))
        quality_factors.append(consistency)
    else:
        quality_factors.append(0.5)

    # Return average quality score
    return sum(quality_factors) / len(quality_factors) if quality_factors else 0.5


def calculate_intrinsic_value(financial_line_items: list, market_cap: float) -> float:
    """
    Calculate intrinsic value using Rakesh Jhunjhunwala's approach:
    - Focus on earnings power and growth
    - Conservative discount rates
    - Quality premium for consistent performers
    """
    if not financial_line_items or not market_cap:
        return None

    try:
        latest = financial_line_items[0]

        # Need positive earnings as base
        if not getattr(latest, 'net_income', None) or latest.net_income <= 0:
            return None

        # Get historical earnings for growth calculation
        net_incomes = [getattr(item, "net_income", None) for item in financial_line_items[:5]
                       if getattr(item, "net_income", None) is not None and getattr(item, "net_income", None) > 0]

        if len(net_incomes) < 2:
            # Use current earnings with conservative multiple for stable companies
            return latest.net_income * 12  # Conservative P/E of 12

        # Calculate sustainable growth rate using historical data
        initial_income = net_incomes[-1]  # Oldest
        final_income = net_incomes[0]     # Latest
        years = len(net_incomes) - 1

        # Calculate historical CAGR
        if initial_income > 0:  # Fixed: Add zero check
            historical_growth = ((final_income / initial_income) ** (1/years) - 1)
        else:
            historical_growth = 0.05  # Default to 5%

        # Conservative growth assumptions (Jhunjhunwala style)
        if historical_growth > 0.25:  # Cap at 25% for sustainability
            sustainable_growth = 0.20  # Conservative 20%
        elif historical_growth > 0.15:
            sustainable_growth = historical_growth * 0.8  # 80% of historical
        elif historical_growth > 0.05:
            sustainable_growth = historical_growth * 0.9  # 90% of historical
        else:
            sustainable_growth = 0.05  # Minimum 5% for inflation

        # Quality assessment affects discount rate
        quality_score = assess_quality_metrics(financial_line_items)

        # Discount rate based on quality (Jhunjhunwala preferred quality)
        if quality_score >= 0.8:  # High quality
            discount_rate = 0.12  # 12% for high quality companies
            terminal_multiple = 18
        elif quality_score >= 0.6:  # Medium quality
            discount_rate = 0.15  # 15% for medium quality
            terminal_multiple = 15
        else:  # Lower quality
            discount_rate = 0.18  # 18% for riskier companies
            terminal_multiple = 12

        # Simple DCF with terminal value
        current_earnings = latest.net_income
        terminal_value = 0
        dcf_value = 0

        # Project 5 years of earnings
        for year in range(1, 6):
            projected_earnings = current_earnings * ((1 + sustainable_growth) ** year)
            present_value = projected_earnings / ((1 + discount_rate) ** year)
            dcf_value += present_value

        # Terminal value (year 5 earnings * terminal multiple)
        year_5_earnings = current_earnings * ((1 + sustainable_growth) ** 5)
        terminal_value = (year_5_earnings * terminal_multiple) / ((1 + discount_rate) ** 5)

        total_intrinsic_value = dcf_value + terminal_value

        return total_intrinsic_value

    except Exception:
        # Fallback to simple earnings multiple
        if getattr(latest, 'net_income', None) and latest.net_income > 0:
            return latest.net_income * 15
        return None


def analyze_rakesh_jhunjhunwala_style(
    financial_line_items: list,
    owner_earnings: float = None,
    intrinsic_value: float = None,
    current_price: float = None,
) -> dict[str, any]:
    """
    Comprehensive analysis in Rakesh Jhunjhunwala's investment style.
    """
    # Run sub-analyses
    profitability = analyze_profitability(financial_line_items)
    growth = analyze_growth(financial_line_items)
    balance_sheet = analyze_balance_sheet(financial_line_items)
    cash_flow = analyze_cash_flow(financial_line_items)
    management = analyze_management_actions(financial_line_items)

    total_score = (
        profitability["score"]
        + growth["score"]
        + balance_sheet["score"]
        + cash_flow["score"]
        + management["score"]
    )

    details = (
        f"Profitability: {profitability['details']}\n"
        f"Growth: {growth['details']}\n"
        f"Balance Sheet: {balance_sheet['details']}\n"
        f"Cash Flow: {cash_flow['details']}\n"
        f"Management Actions: {management['details']}"
    )

    # Use provided intrinsic value or calculate if not provided
    if not intrinsic_value:
        intrinsic_value = calculate_intrinsic_value(financial_line_items, current_price)

    valuation_gap = None
    if intrinsic_value and current_price:
        valuation_gap = intrinsic_value - current_price

    return {
        "total_score": total_score,
        "details": details,
        "owner_earnings": owner_earnings,
        "intrinsic_value": intrinsic_value,
        "current_price": current_price,
        "valuation_gap": valuation_gap,
        "breakdown": {
            "profitability": profitability,
            "growth": growth,
            "balance_sheet": balance_sheet,
            "cash_flow": cash_flow,
            "management": management,
        },
    }
