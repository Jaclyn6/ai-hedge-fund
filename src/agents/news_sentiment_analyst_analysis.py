"""Pure analyzer functions for the news-sentiment analyst.

Extracted from `news_sentiment.py` so they can be imported without pulling in
LangChain / LangGraph. The v1 agent called an LLM to classify any article whose
`sentiment` field was missing. In the Claude-Code-native flow the subagent
itself is the LLM, so this analyzer instead:

  * aggregates pre-classified news into bullish/bearish/neutral counts
  * surfaces up to 10 most-recent untagged headlines so the subagent can
    classify them from its own reading of the titles

The subagent then reconciles both into a final signal + confidence.
"""
from __future__ import annotations

from typing import Any


_MAX_UNCLASSIFIED_TITLES = 10


def analyze_news_sentiment_quant(company_news: list) -> dict[str, Any]:
    """Aggregate pre-classified news into signal counts and expose untagged titles."""
    if not company_news:
        return {
            "signal": "neutral",
            "confidence": 0,
            "reasoning": {
                "news_sentiment": {
                    "signal": "neutral",
                    "confidence": 0,
                    "metrics": {
                        "total_articles": 0,
                        "bullish_articles": 0,
                        "bearish_articles": 0,
                        "neutral_articles": 0,
                        "unclassified_articles": 0,
                    },
                },
                "unclassified_titles": [],
                "data_warning": "Insufficient data: no company news available",
            },
        }

    bullish = 0
    bearish = 0
    neutral = 0
    unclassified: list[dict[str, Any]] = []

    for news in company_news:
        sentiment = getattr(news, "sentiment", None)
        if sentiment is None:
            if len(unclassified) < _MAX_UNCLASSIFIED_TITLES:
                unclassified.append(
                    {
                        "title": getattr(news, "title", "") or "",
                        "date": str(getattr(news, "date", "") or ""),
                        "source": getattr(news, "source", "") or "",
                    }
                )
            continue

        s = str(sentiment).lower()
        if s == "negative":
            bearish += 1
        elif s == "positive":
            bullish += 1
        else:
            neutral += 1

    classified_total = bullish + bearish + neutral

    if bullish > bearish:
        overall = "bullish"
    elif bearish > bullish:
        overall = "bearish"
    else:
        overall = "neutral"

    confidence = 0.0
    if classified_total > 0:
        confidence = round(max(bullish, bearish) / classified_total * 100, 2)

    reasoning: dict[str, Any] = {
        "news_sentiment": {
            "signal": overall,
            "confidence": confidence,
            "metrics": {
                "total_articles": classified_total + len(unclassified),
                "bullish_articles": bullish,
                "bearish_articles": bearish,
                "neutral_articles": neutral,
                "unclassified_articles": len(unclassified),
            },
        },
        "unclassified_titles": unclassified,
    }

    if classified_total == 0 and not unclassified:
        reasoning["data_warning"] = (
            "Insufficient data: no news sentiment available (article list empty)"
        )

    return {
        "signal": overall,
        "confidence": confidence,
        "reasoning": reasoning,
    }
