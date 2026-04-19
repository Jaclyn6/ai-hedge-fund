"""Pure analyzer functions for the quantitative sentiment analyst.

Extracted from `sentiment.py` so they can be imported without pulling in
LangChain / LangGraph. The original agent module can re-use these, and the MCP
server in `mcp_server/` imports from here directly.

Combines insider trades (30% weight) with pre-classified news sentiment
(70% weight) into a single bullish/bearish/neutral signal.
"""
from __future__ import annotations

from typing import Any


_INSIDER_WEIGHT = 0.3
_NEWS_WEIGHT = 0.7


def _classify_insider_trades(insider_trades: list) -> list[str]:
    """Tag each insider trade bullish (buy) or bearish (sell) from transaction_shares sign."""
    signals: list[str] = []
    for trade in insider_trades or []:
        shares = getattr(trade, "transaction_shares", None)
        if shares is None:
            continue
        signals.append("bearish" if shares < 0 else "bullish")
    return signals


def _classify_news_sentiment(company_news: list) -> list[str]:
    """Tag each news item bullish/bearish/neutral from its pre-classified sentiment field."""
    signals: list[str] = []
    for news in company_news or []:
        sentiment = getattr(news, "sentiment", None)
        if sentiment is None:
            continue
        s = str(sentiment).lower()
        if s == "negative":
            signals.append("bearish")
        elif s == "positive":
            signals.append("bullish")
        else:
            signals.append("neutral")
    return signals


def analyze_sentiment_combined(
    insider_trades: list,
    company_news: list,
) -> dict[str, Any]:
    """Weighted combination of insider trades (30%) + news sentiment (70%).

    Returns {signal, confidence, reasoning} matching the native-layer contract.
    """
    insider_signals = _classify_insider_trades(insider_trades)
    news_signals = _classify_news_sentiment(company_news)

    insider_bullish = insider_signals.count("bullish")
    insider_bearish = insider_signals.count("bearish")
    news_bullish = news_signals.count("bullish")
    news_bearish = news_signals.count("bearish")
    news_neutral = news_signals.count("neutral")

    weighted_bullish = (
        insider_bullish * _INSIDER_WEIGHT
        + news_bullish * _NEWS_WEIGHT
    )
    weighted_bearish = (
        insider_bearish * _INSIDER_WEIGHT
        + news_bearish * _NEWS_WEIGHT
    )

    if weighted_bullish > weighted_bearish:
        overall = "bullish"
    elif weighted_bearish > weighted_bullish:
        overall = "bearish"
    else:
        overall = "neutral"

    total_weighted = (
        len(insider_signals) * _INSIDER_WEIGHT
        + len(news_signals) * _NEWS_WEIGHT
    )
    confidence = 0.0
    if total_weighted > 0:
        confidence = round(
            max(weighted_bullish, weighted_bearish) / total_weighted * 100,
            2,
        )

    def _agg_signal(bullish: int, bearish: int) -> str:
        if bullish > bearish:
            return "bullish"
        if bearish > bullish:
            return "bearish"
        return "neutral"

    reasoning = {
        "insider_trading": {
            "signal": _agg_signal(insider_bullish, insider_bearish),
            "confidence": round(
                max(insider_bullish, insider_bearish)
                / max(len(insider_signals), 1)
                * 100
            ),
            "metrics": {
                "total_trades": len(insider_signals),
                "bullish_trades": insider_bullish,
                "bearish_trades": insider_bearish,
                "weight": _INSIDER_WEIGHT,
                "weighted_bullish": round(insider_bullish * _INSIDER_WEIGHT, 1),
                "weighted_bearish": round(insider_bearish * _INSIDER_WEIGHT, 1),
            },
        },
        "news_sentiment": {
            "signal": _agg_signal(news_bullish, news_bearish),
            "confidence": round(
                max(news_bullish, news_bearish)
                / max(len(news_signals), 1)
                * 100
            ),
            "metrics": {
                "total_articles": len(news_signals),
                "bullish_articles": news_bullish,
                "bearish_articles": news_bearish,
                "neutral_articles": news_neutral,
                "weight": _NEWS_WEIGHT,
                "weighted_bullish": round(news_bullish * _NEWS_WEIGHT, 1),
                "weighted_bearish": round(news_bearish * _NEWS_WEIGHT, 1),
            },
        },
        "combined_analysis": {
            "total_weighted_bullish": round(weighted_bullish, 1),
            "total_weighted_bearish": round(weighted_bearish, 1),
            "signal_determination": (
                f"{overall.capitalize()} based on weighted signal comparison"
            ),
        },
    }

    # Surface data-availability warning for the guardrail layer.
    if not insider_signals and not news_signals:
        reasoning["data_warning"] = (
            "Insufficient data: no insider trades and no news sentiment available"
        )

    return {
        "signal": overall,
        "confidence": confidence,
        "reasoning": reasoning,
    }
