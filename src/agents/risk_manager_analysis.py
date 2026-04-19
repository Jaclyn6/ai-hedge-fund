"""Pure risk-management analyzer functions.

Volatility- and correlation-adjusted position sizing. Extracted from the v1
LangGraph agent (`src/agents/risk_manager.py`) so the Claude Code native
layer (MCP + subagents) can call the same math without any LangChain
dependency. Both paths share this module.

Public entry point: `analyze_risk(tickers, end_date, portfolio, start_date=None)`.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from src.tools.api import get_prices, prices_to_df


DEFAULT_PORTFOLIO: dict = {
    "cash": 100_000.0,
    "positions": {},
    "margin_requirement": 0.5,
    "margin_used": 0.0,
}


def _default_start_date(end_date: str, lookback_days: int = 180) -> str:
    """Default start_date = end_date − lookback_days (180 days gives us 30-day rolling percentile over ~5 months of trading data)."""
    try:
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except Exception:
        end = datetime.today()
    start = end - timedelta(days=lookback_days)
    return start.strftime("%Y-%m-%d")


def calculate_volatility_metrics(prices_df: pd.DataFrame, lookback_days: int = 60) -> dict:
    """Daily + annualized volatility + historical percentile. Mirror of v1."""
    if prices_df is None or prices_df.empty or len(prices_df) < 2:
        return {
            "daily_volatility": 0.05,
            "annualized_volatility": 0.05 * float(np.sqrt(252)),
            "volatility_percentile": 100.0,
            "data_points": 0 if prices_df is None else len(prices_df),
        }

    daily_returns = prices_df["close"].pct_change().dropna()
    if len(daily_returns) < 2:
        return {
            "daily_volatility": 0.05,
            "annualized_volatility": 0.05 * float(np.sqrt(252)),
            "volatility_percentile": 100.0,
            "data_points": len(daily_returns),
        }

    recent_returns = daily_returns.tail(min(lookback_days, len(daily_returns)))
    daily_vol = recent_returns.std()
    annualized_vol = daily_vol * float(np.sqrt(252))

    if len(daily_returns) >= 30:
        rolling_vol = daily_returns.rolling(window=30).std().dropna()
        if len(rolling_vol) > 0:
            current_vol_percentile = (rolling_vol <= daily_vol).mean() * 100.0
        else:
            current_vol_percentile = 50.0
    else:
        current_vol_percentile = 50.0

    def _clean(val, default):
        try:
            return float(val) if not np.isnan(val) else default
        except (TypeError, ValueError):
            return default

    return {
        "daily_volatility": _clean(daily_vol, 0.025),
        "annualized_volatility": _clean(annualized_vol, 0.25),
        "volatility_percentile": _clean(current_vol_percentile, 50.0),
        "data_points": int(len(recent_returns)),
    }


def calculate_volatility_adjusted_limit(annualized_volatility: float) -> float:
    """Map annualized volatility → position-limit pct of portfolio.

    Low vol (<15%): up to 25%. Medium (15-30%): ~20%→12.5%. High (30-50%):
    ~15%→5%. Very high (>50%): ~10%. Bounds enforced to [5%, 25%].
    """
    base_limit = 0.20

    if annualized_volatility < 0.15:
        vol_multiplier = 1.25
    elif annualized_volatility < 0.30:
        vol_multiplier = 1.0 - (annualized_volatility - 0.15) * 0.5
    elif annualized_volatility < 0.50:
        vol_multiplier = 0.75 - (annualized_volatility - 0.30) * 0.5
    else:
        vol_multiplier = 0.50

    vol_multiplier = max(0.25, min(1.25, vol_multiplier))
    return base_limit * vol_multiplier


def calculate_correlation_multiplier(avg_correlation: float) -> float:
    """Map avg correlation with active book → position limit multiplier."""
    if avg_correlation >= 0.80:
        return 0.70
    if avg_correlation >= 0.60:
        return 0.85
    if avg_correlation >= 0.40:
        return 1.00
    if avg_correlation >= 0.20:
        return 1.05
    return 1.10


def analyze_risk(
    tickers: list[str],
    end_date: str,
    portfolio: dict | None = None,
    start_date: str | None = None,
) -> dict:
    """Per-ticker volatility + correlation → remaining position limit.

    Returns `{ticker: {remaining_position_limit, current_price,
    volatility_metrics, correlation_metrics, reasoning}}` plus a
    `_meta` block with total portfolio value and any per-ticker fetch
    warnings. The wrapper is responsible for translating `_meta.warnings`
    into a `data_quality` block.
    """
    portfolio = portfolio if portfolio is not None else dict(DEFAULT_PORTFOLIO)
    if start_date is None:
        start_date = _default_start_date(end_date)

    all_tickers = set(tickers) | set(portfolio.get("positions", {}).keys())
    current_prices: dict[str, float] = {}
    volatility_data: dict[str, dict] = {}
    returns_by_ticker: dict[str, pd.Series] = {}
    warnings: list[str] = []

    for ticker in all_tickers:
        try:
            prices = get_prices(ticker=ticker, start_date=start_date, end_date=end_date)
        except Exception as exc:
            warnings.append(f"{ticker}: price fetch failed ({exc})")
            prices = None

        if not prices:
            warnings.append(f"{ticker}: no price data available")
            volatility_data[ticker] = {
                "daily_volatility": 0.05,
                "annualized_volatility": 0.05 * float(np.sqrt(252)),
                "volatility_percentile": 100.0,
                "data_points": 0,
            }
            continue

        prices_df = prices_to_df(prices)
        if prices_df.empty or len(prices_df) < 2:
            warnings.append(f"{ticker}: insufficient price data ({len(prices_df)} rows)")
            current_prices[ticker] = 0.0
            volatility_data[ticker] = {
                "daily_volatility": 0.05,
                "annualized_volatility": 0.05 * float(np.sqrt(252)),
                "volatility_percentile": 100.0,
                "data_points": int(len(prices_df)),
            }
            continue

        current_prices[ticker] = float(prices_df["close"].iloc[-1])
        volatility_data[ticker] = calculate_volatility_metrics(prices_df)

        daily_returns = prices_df["close"].pct_change().dropna()
        if len(daily_returns) > 0:
            returns_by_ticker[ticker] = daily_returns

    correlation_matrix = None
    if len(returns_by_ticker) >= 2:
        try:
            returns_df = pd.DataFrame(returns_by_ticker).dropna(how="any")
            if returns_df.shape[1] >= 2 and returns_df.shape[0] >= 5:
                correlation_matrix = returns_df.corr()
        except Exception:
            correlation_matrix = None

    active_positions = {
        t for t, pos in portfolio.get("positions", {}).items()
        if abs(pos.get("long", 0) - pos.get("short", 0)) > 0
    }

    total_portfolio_value = float(portfolio.get("cash", 0.0))
    for t, pos in portfolio.get("positions", {}).items():
        if t in current_prices:
            total_portfolio_value += pos.get("long", 0) * current_prices[t]
            total_portfolio_value -= pos.get("short", 0) * current_prices[t]

    risk_analysis: dict = {}
    for ticker in tickers:
        if ticker not in current_prices or current_prices[ticker] <= 0:
            risk_analysis[ticker] = {
                "remaining_position_limit": 0.0,
                "current_price": 0.0,
                "volatility_metrics": volatility_data.get(ticker, {}),
                "correlation_metrics": {
                    "avg_correlation_with_active": None,
                    "max_correlation_with_active": None,
                    "top_correlated_tickers": [],
                },
                "reasoning": {"error": "Missing price data for risk calculation"},
            }
            continue

        price = current_prices[ticker]
        vol_data = volatility_data.get(ticker, {})

        position = portfolio.get("positions", {}).get(ticker, {})
        long_value = position.get("long", 0) * price
        short_value = position.get("short", 0) * price
        current_position_value = abs(long_value - short_value)

        vol_adjusted_limit_pct = calculate_volatility_adjusted_limit(
            vol_data.get("annualized_volatility", 0.25)
        )

        corr_metrics = {
            "avg_correlation_with_active": None,
            "max_correlation_with_active": None,
            "top_correlated_tickers": [],
        }
        corr_multiplier = 1.0
        if correlation_matrix is not None and ticker in correlation_matrix.columns:
            comparable = [t for t in active_positions if t in correlation_matrix.columns and t != ticker]
            if not comparable:
                comparable = [t for t in correlation_matrix.columns if t != ticker]
            if comparable:
                series = correlation_matrix.loc[ticker, comparable].dropna()
                if len(series) > 0:
                    avg_corr = float(series.mean())
                    max_corr = float(series.max())
                    corr_metrics["avg_correlation_with_active"] = avg_corr
                    corr_metrics["max_correlation_with_active"] = max_corr
                    top_corr = series.sort_values(ascending=False).head(3)
                    corr_metrics["top_correlated_tickers"] = [
                        {"ticker": idx, "correlation": float(val)} for idx, val in top_corr.items()
                    ]
                    corr_multiplier = calculate_correlation_multiplier(avg_corr)

        combined_limit_pct = vol_adjusted_limit_pct * corr_multiplier
        position_limit = total_portfolio_value * combined_limit_pct
        remaining_position_limit = position_limit - current_position_value
        max_position_size = min(remaining_position_limit, portfolio.get("cash", 0.0))

        risk_analysis[ticker] = {
            "remaining_position_limit": float(max_position_size),
            "current_price": float(price),
            "volatility_metrics": {
                "daily_volatility": float(vol_data.get("daily_volatility", 0.05)),
                "annualized_volatility": float(vol_data.get("annualized_volatility", 0.25)),
                "volatility_percentile": float(vol_data.get("volatility_percentile", 100.0)),
                "data_points": int(vol_data.get("data_points", 0)),
            },
            "correlation_metrics": corr_metrics,
            "reasoning": {
                "portfolio_value": float(total_portfolio_value),
                "current_position_value": float(current_position_value),
                "base_position_limit_pct": float(vol_adjusted_limit_pct),
                "correlation_multiplier": float(corr_multiplier),
                "combined_position_limit_pct": float(combined_limit_pct),
                "position_limit": float(position_limit),
                "remaining_limit": float(remaining_position_limit),
                "available_cash": float(portfolio.get("cash", 0.0)),
                "risk_adjustment": (
                    f"Volatility x Correlation adjusted: {combined_limit_pct:.1%} "
                    f"(base {vol_adjusted_limit_pct:.1%})"
                ),
            },
        }

    risk_analysis["_meta"] = {
        "total_portfolio_value": float(total_portfolio_value),
        "start_date": start_date,
        "end_date": end_date,
        "warnings": warnings,
    }
    return risk_analysis
