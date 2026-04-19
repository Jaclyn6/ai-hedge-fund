"""Pure analyzer functions for a short-term technical analyst.

Price/volume/momentum/trend/volatility only. No fundamentals. Designed to
fill the short-term (<3M) perspective in the hedge-fund roster.

The MCP server imports these directly; they have no LangChain dependency.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


def _safe_float(value, default: float = 0.0) -> float:
    try:
        if pd.isna(value) or np.isnan(value):
            return default
        return float(value)
    except (ValueError, TypeError, OverflowError):
        return default


def analyze_momentum(prices_df: pd.DataFrame) -> dict:
    """Multi-horizon price momentum: 1M / 3M / 6M / 12M returns.

    Weighted average of per-window scores, with short windows weighted
    heavier (matches a short-term lens).
    """
    if prices_df.empty or "close" not in prices_df.columns or len(prices_df) < 21:
        return {"score": 0, "max_score": 10, "details": "Insufficient price history for momentum analysis"}

    closes = prices_df["close"].astype(float).reset_index(drop=True)
    last = _safe_float(closes.iloc[-1])
    if last <= 0:
        return {"score": 0, "max_score": 10, "details": "Invalid latest close price"}

    windows = [("1M", 21, 0.40), ("3M", 63, 0.30), ("6M", 126, 0.20), ("12M", 252, 0.10)]
    weighted = 0.0
    weight_used = 0.0
    details: list[str] = []

    for label, days, weight in windows:
        if len(closes) <= days:
            continue
        past = _safe_float(closes.iloc[-1 - days])
        if past <= 0:
            continue
        ret = (last - past) / past
        if ret > 0.15:
            s = 10.0
        elif ret > 0.05:
            s = 7.5
        elif ret > 0:
            s = 6.0
        elif ret > -0.05:
            s = 4.0
        elif ret > -0.15:
            s = 2.0
        else:
            s = 0.0
        weighted += s * weight
        weight_used += weight
        details.append(f"{label} return {ret:.1%}")

    if weight_used == 0:
        return {"score": 0, "max_score": 10, "details": "Insufficient history across all momentum windows"}

    final_score = weighted / weight_used
    return {"score": round(final_score, 2), "max_score": 10, "details": "; ".join(details)}


def analyze_trend(prices_df: pd.DataFrame) -> dict:
    """Price vs 20/50/200-day simple moving averages.

    Weight each MA by its duration (20: 2 pts, 50: 3 pts, 200: 5 pts) so
    being above the 200d carries the most signal.
    """
    if prices_df.empty or "close" not in prices_df.columns or len(prices_df) < 20:
        return {"score": 0, "max_score": 10, "details": "Insufficient data for trend analysis"}

    closes = prices_df["close"].astype(float)
    last = _safe_float(closes.iloc[-1])
    if last <= 0:
        return {"score": 0, "max_score": 10, "details": "Invalid latest close"}

    ma20 = _safe_float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else None
    ma50 = _safe_float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else None
    ma200 = _safe_float(closes.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else None

    details: list[str] = []
    score = 0.0
    max_parts = 0

    if ma20 and ma20 > 0:
        above = last > ma20
        details.append(f"Price {'above' if above else 'below'} 20d MA ({last:.2f} vs {ma20:.2f})")
        score += 2.0 if above else 0.0
        max_parts += 2

    if ma50 and ma50 > 0:
        above = last > ma50
        details.append(f"Price {'above' if above else 'below'} 50d MA ({last:.2f} vs {ma50:.2f})")
        score += 3.0 if above else 0.0
        max_parts += 3

    if ma200 and ma200 > 0:
        above = last > ma200
        details.append(f"Price {'above' if above else 'below'} 200d MA ({last:.2f} vs {ma200:.2f})")
        score += 5.0 if above else 0.0
        max_parts += 5

    if max_parts == 0:
        return {"score": 0, "max_score": 10, "details": "Insufficient data for trend analysis"}

    if ma50 and ma200 and ma50 > 0 and ma200 > 0:
        if ma50 > ma200:
            details.append("Golden-cross regime (50d > 200d)")
        else:
            details.append("Death-cross regime (50d < 200d)")

    final_score = (score / max_parts) * 10
    return {"score": round(final_score, 2), "max_score": 10, "details": "; ".join(details)}


def analyze_rsi(prices_df: pd.DataFrame, period: int = 14) -> dict:
    """Wilder RSI(14). Interpreted for short-term trend followers."""
    if prices_df.empty or "close" not in prices_df.columns or len(prices_df) < period + 1:
        return {"score": 0, "max_score": 10, "details": "Insufficient data for RSI analysis"}

    closes = prices_df["close"].astype(float)
    delta = closes.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi_value = _safe_float(rsi.iloc[-1], default=50.0)

    if rsi_value >= 80:
        score = 5.5
        regime = "extremely overbought (parabolic, mean-reversion risk)"
    elif rsi_value >= 70:
        score = 7.5
        regime = "overbought but trending (stretched)"
    elif rsi_value >= 60:
        score = 8.5
        regime = "strong bullish momentum"
    elif rsi_value >= 50:
        score = 7.0
        regime = "bullish bias"
    elif rsi_value >= 40:
        score = 4.0
        regime = "bearish bias"
    elif rsi_value >= 30:
        score = 2.5
        regime = "weak / downtrend"
    elif rsi_value >= 20:
        score = 3.5
        regime = "oversold (bounce setup but falling-knife risk)"
    else:
        score = 2.5
        regime = "extremely oversold (panic)"

    return {
        "score": round(score, 2),
        "max_score": 10,
        "details": f"RSI(14) = {rsi_value:.1f} — {regime}",
    }


def analyze_volatility_regime(prices_df: pd.DataFrame) -> dict:
    """21d realized vol (annualized) and its ratio to 12M baseline, plus ATR%."""
    if prices_df.empty or "close" not in prices_df.columns or len(prices_df) < 30:
        return {"score": 0, "max_score": 10, "details": "Insufficient data for volatility regime analysis"}

    closes = prices_df["close"].astype(float)
    returns = closes.pct_change().dropna()
    if len(returns) < 21:
        return {"score": 0, "max_score": 10, "details": "Insufficient returns for volatility regime"}

    recent_vol = _safe_float(returns.tail(21).std() * math.sqrt(252))
    full_vol = _safe_float(returns.std() * math.sqrt(252))
    ratio = recent_vol / full_vol if full_vol > 0 else 1.0

    details = [
        f"21d realized vol (annualized): {recent_vol:.1%}",
        f"12M baseline vol: {full_vol:.1%}",
        f"regime ratio {ratio:.2f}x",
    ]

    if 0.7 <= ratio <= 1.3:
        score = 7.0
        details.append("stable vol regime — conducive to directional trades")
    elif ratio < 0.7:
        score = 5.0
        details.append("suppressed vol — complacency (turkey-problem risk)")
    elif ratio <= 2.0:
        score = 4.0
        details.append("elevated vol — caution on sizing")
    else:
        score = 2.0
        details.append("extreme vol — crisis regime")

    if all(col in prices_df.columns for col in ("high", "low", "close")) and len(prices_df) >= 15:
        high = prices_df["high"].astype(float)
        low = prices_df["low"].astype(float)
        close = prices_df["close"].astype(float)
        prev_close = close.shift(1)
        tr = pd.concat(
            [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
        ).max(axis=1)
        atr14 = _safe_float(tr.rolling(14).mean().iloc[-1])
        if atr14 > 0 and close.iloc[-1] > 0:
            atr_pct = atr14 / float(close.iloc[-1])
            details.append(f"ATR%(14) = {atr_pct:.2%}")

    return {"score": round(score, 2), "max_score": 10, "details": "; ".join(details)}


def analyze_drawdown(prices_df: pd.DataFrame) -> dict:
    """Max drawdown over the most recent ~21 trading days (1M)."""
    if prices_df.empty or "close" not in prices_df.columns or len(prices_df) < 21:
        return {"score": 0, "max_score": 10, "details": "Insufficient data for drawdown analysis"}

    closes = prices_df["close"].astype(float).tail(21)
    running_max = closes.cummax()
    drawdown = (closes - running_max) / running_max
    max_dd = _safe_float(drawdown.min())

    if max_dd > -0.03:
        score, regime = 9.0, "very shallow drawdown"
    elif max_dd > -0.07:
        score, regime = 7.5, "shallow drawdown"
    elif max_dd > -0.12:
        score, regime = 5.0, "moderate drawdown"
    elif max_dd > -0.20:
        score, regime = 3.0, "significant drawdown"
    else:
        score, regime = 1.0, "severe drawdown"

    return {
        "score": round(score, 2),
        "max_score": 10,
        "details": f"1M max drawdown {max_dd:.1%} — {regime}",
    }


def analyze_volume_trend(prices_df: pd.DataFrame) -> dict:
    """20d avg volume vs 100d avg volume, cross-checked against 1M price move."""
    if prices_df.empty or "volume" not in prices_df.columns or len(prices_df) < 100:
        return {"score": 0, "max_score": 10, "details": "Insufficient data for volume trend analysis"}

    vol = prices_df["volume"].astype(float)
    recent = _safe_float(vol.tail(20).mean())
    baseline = _safe_float(vol.tail(100).mean())
    if baseline <= 0:
        return {"score": 0, "max_score": 10, "details": "Baseline volume is zero"}

    ratio = recent / baseline
    closes = prices_df["close"].astype(float)
    recent_return = (
        _safe_float(closes.iloc[-1]) / _safe_float(closes.iloc[-21]) - 1
        if len(closes) >= 21 and _safe_float(closes.iloc[-21]) > 0
        else 0.0
    )

    details = [f"20d vol vs 100d vol: {ratio:.2f}x", f"1M return: {recent_return:.1%}"]

    if ratio > 1.2 and recent_return > 0.03:
        score = 8.0
        details.append("rising volume confirms uptrend")
    elif ratio > 1.2 and recent_return < -0.03:
        score = 3.0
        details.append("rising volume on decline — distribution risk")
    elif 0.8 <= ratio <= 1.2:
        score = 5.5
        details.append("normal volume regime")
    elif ratio < 0.8:
        score = 4.0
        details.append("declining volume — waning interest")
    else:
        score = 5.0
        details.append("mixed volume signal")

    return {"score": round(score, 2), "max_score": 10, "details": "; ".join(details)}


# Composite weights used by the MCP tool wrapper. Exposed for transparency.
TECHNICAL_WEIGHTS = {
    "momentum": 0.35,
    "trend": 0.25,
    "rsi": 0.15,
    "volatility_regime": 0.10,
    "drawdown": 0.10,
    "volume_trend": 0.05,
}
