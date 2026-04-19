---
description: Run the AI hedge fund on one or more tickers, collecting signals from every available investor subagent in parallel and producing a final consolidated recommendation per ticker.
argument-hint: TICKER[,TICKER...] [YYYY-MM-DD]
---

# /hedge-fund

Orchestrate the investor subagents for the tickers in `$ARGUMENTS`.

## Parsing arguments

`$ARGUMENTS` is a comma-separated list of tickers, optionally followed by a date in `YYYY-MM-DD` format.

Examples:
- `AAPL` → ticker `AAPL`, end_date today
- `AAPL,MSFT,NVDA` → three tickers, end_date today
- `AAPL 2025-03-31` → ticker `AAPL`, end_date `2025-03-31`
- `AAPL,MSFT 2024-12-31` → two tickers, end_date `2024-12-31`

If no date is given, default to **the most recent completed month-end** (e.g. if today is 2026-04-19, use `2026-03-31`). Do not ask the user, and do not use today's date — the free-tier financial data source gates `market_cap` on the current-day endpoint, so using today produces null valuations. Month-end dates hit the historical endpoint which is fully populated for AAPL, GOOGL, MSFT, NVDA, TSLA.

## Execution

For each ticker, dispatch **both** investor subagents **in parallel**. Use a single message containing multiple Agent tool calls — do not serialize.

Available investor subagents (grow this list as more are added to `.claude/agents/`):
- `warren-buffett` — quality + moat + intrinsic value
- `ben-graham` — margin of safety + Graham Number + balance sheet strength
- `charlie-munger` — mental models, moat, predictability, fair price for wonderful businesses
- `michael-burry` — deep value, contrarian, FCF yield focus, catalyst-aware
- `cathie-wood` — disruptive innovation, 5-year growth horizon, high R&D intensity
- `bill-ackman` — activist investor, high-quality businesses, concentrated bets with catalysts
- `peter-lynch` — GARP (growth at reasonable price), PEG ratio, ten-bagger hunting
- `aswath-damodaran` — "Dean of Valuation," story + numbers + disciplined DCF with CAPM cost of equity
- `phil-fisher` — meticulous growth + 15 Points, scuttlebutt-style deep quality research
- `mohnish-pabrai` — Dhandho investor, "heads I win / tails I don't lose much," low-risk doubles
- `rakesh-jhunjhunwala` — Big Bull of India, patient long-term growth conviction
- `stanley-druckenmiller` — macro/momentum + asymmetric risk-reward setups
- `nassim-taleb` — tail risk, antifragility, barbell strategy, Black Swan sentinel

For each subagent call, pass a prompt like:
```
Analyze {ticker} for end_date {end_date}. Return only the final JSON signal block, no prose.
```

## Aggregating signals

After all subagents return, parse each one's JSON output into `{ticker, signal, confidence, reasoning}`. Build a per-ticker signal matrix.

Decide a final recommendation per ticker using these rules:

| Consensus across investors | Final signal | Action |
|---|---|---|
| All bullish | **strong buy** | buy |
| Majority bullish, none bearish | **buy** | buy |
| All bearish | **strong sell** | sell |
| Majority bearish, none bullish | **sell** | sell |
| Bullish and bearish split | **neutral** | hold |
| All neutral | **neutral** | hold |

Confidence for the final call = mean of contributing investors' confidences, rounded.

## Output format

Present one consolidated markdown report to the user. Structure:

```markdown
## Hedge Fund Analysis — {end_date}

### {TICKER_1}

| Investor | Signal | Confidence | Reasoning |
|---|---|---|---|
| Warren Buffett | bullish | 72 | ... |
| Ben Graham | neutral | 45 | ... |

**Final call: neutral (hold)** — confidence 58. Mixed consensus; Buffett sees moat quality but Graham flags no margin of safety vs Graham Number.

### {TICKER_2}

(same structure)
```

End with a one-line summary across all tickers if there's more than one: `Portfolio summary: 1 buy (MSFT), 1 hold (AAPL), 0 sell.`

## Data-quality handling

If every investor returns neutral with low confidence (<40) due to insufficient data, the ticker likely isn't on the free tier. In that case, clearly state at the top of the report: `⚠️ {TICKER}: financial data unavailable without FINANCIAL_DATASETS_API_KEY. Only AAPL, GOOGL, MSFT, NVDA, TSLA work on the free tier.`

Do not fabricate analysis when data is missing — surface the limitation.
