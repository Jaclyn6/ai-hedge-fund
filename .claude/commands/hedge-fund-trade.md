---
description: Run the AI hedge fund in TRADE mode — dispatch all 19 signal subagents, aggregate multi-horizon consensus, then run the portfolio-manager to produce concrete {action, quantity} decisions per ticker. Unlike `/hedge-fund` (view-only), this sizes positions.
argument-hint: TICKER[,TICKER...] [YYYY-MM-DD] [--cash N] [--positions JSON]
---

# /hedge-fund-trade

Produce **actual trade decisions** (buy/sell/short/cover/hold + share quantity) for the tickers in `$ARGUMENTS`. This is the Phase 2 trade-execution orchestrator — it wraps `/hedge-fund`'s signal-collection pass and feeds the output into the `portfolio-manager` subagent for position sizing.

## Parsing arguments

`$ARGUMENTS` is a comma-separated list of tickers, optionally followed by:
- A date in `YYYY-MM-DD` format (defaults to today)
- `--cash N` flag to override starting cash (defaults to 100000)
- `--positions JSON` inline JSON `{ticker: {long: N, short: N}}` for existing positions (defaults to empty)

Examples:
- `AAPL` → ticker AAPL, today, $100k cash, no positions
- `AAPL,MSFT 2026-03-31` → 2 tickers, end_date `2026-03-31`
- `AAPL --cash 50000` → $50k cash
- `AAPL --cash 100000 --positions {"AAPL":{"long":30}}` → 30 shares of AAPL already held

If no date is given, default to **today's date** — do not ask. If `--cash` is missing use 100000. If `--positions` is missing use `{}`.

## Phase 1 — signal collection (same as `/hedge-fund`)

Dispatch **every** signal subagent below **in parallel** — single message with one Agent tool call per subagent per ticker. Follow the horizon bucketing from `/hedge-fund`:

| Horizon | Subagents |
|---|---|
| **Short (<3M)** | `stanley-druckenmiller`, `technical-analyst`, `sentiment-analyst`, `news-sentiment-analyst` |
| **Mid (3M–2Y)** | `michael-burry`, `cathie-wood`, `bill-ackman`, `peter-lynch`, `mohnish-pabrai`, `growth-analyst` |
| **Long (>2Y)** | `warren-buffett`, `ben-graham`, `charlie-munger`, `aswath-damodaran`, `phil-fisher`, `rakesh-jhunjhunwala`, `nassim-taleb`, `valuation-analyst`, `fundamentals-analyst` |

For each subagent call, pass:
```
Analyze {ticker} for end_date {end_date}. Return only the final JSON signal block, no prose.
```

Parse each subagent's JSON output into `{investor, signal, confidence, reasoning}`.

## Phase 2 — bucket consensus

For each ticker, for each bucket, compute `{bucket_signal, bucket_confidence}`:
- Ignore `unavailable` votes.
- Consensus rules (same as `/hedge-fund`):
  | Bucket consensus | Bucket signal |
  |---|---|
  | All bullish | strong buy |
  | Majority bullish, none bearish | buy |
  | All bearish | strong sell |
  | Majority bearish, none bullish | sell |
  | Bullish and bearish mixed | neutral |
  | All neutral | neutral |
  | All `unavailable` | unavailable |
- `bucket_confidence` = mean of contributing confidences (excluding unavailable), rounded.

## Phase 3 — portfolio-manager decision

Dispatch the `portfolio-manager` subagent **once** with the aggregated signals. Prompt template:

```
Decide trades for tickers {tickers} at end_date {end_date}.

Portfolio state:
- cash: {cash}
- positions: {positions}

Signals per ticker (full per-analyst payload for conviction math):
{signals_by_ticker as JSON}

Per-ticker bucket consensus (for horizon weighting):
{bucket_consensus as JSON}

Call mcp__hedgefund__portfolio_decision_inputs with tickers, signals_by_ticker, end_date, and portfolio. Then produce the final {ticker: {action, quantity, confidence, reasoning}} JSON.
```

Where `signals_by_ticker` is the full `{ticker: {agent_name: {sig, conf}}}` map and `bucket_consensus` is `{ticker: {short: {signal, confidence}, mid: {...}, long: {...}}}`.

## Output format

Default to Korean when the user's most recent message was in Korean; otherwise English.

```markdown
## Hedge Fund Trade Decisions — {end_date}

**Portfolio:** cash ${cash}, {n} existing positions. Value: ${portfolio_value}.

### Signal summary (per bucket)

| Ticker | 단기 / Short | 중기 / Mid | 장기 / Long |
|---|---|---|---|
| AAPL | buy (62) | neutral (45) | buy (71) |
| NVDA | neutral (50) | buy (68) | buy (74) |

### Trade decisions

| Ticker | Action | Qty | Confidence | Limit ($) | Reasoning |
|---|---|---|---|---|---|
| AAPL | **buy** | 42 | 68 | $18,922 | Conviction +0.52 across 3 buckets; ann vol 26%, base 19%. 60% of max 70. |
| NVDA | **hold** | 0 | 40 | $12,500 | Short-term mixed vs long-term bullish. Conviction +0.12 — wait. |

### Risk notes

{portfolio-manager's risk_notes line, e.g. volatility + correlation context, any data_quality warnings.}

### Final summary

**Total trade count:** 1 buy / 0 sell / 0 short / 0 cover / 1 hold.
**Capital deployed:** ${sum(qty × price for buys)}.
**Capital remaining:** ${cash − capital_deployed}.
```

If multiple tickers and some returned `unavailable`, show them in the signal table with dashes in the decisions table + `action: hold, qty: 0, confidence: 0, reasoning: "No valid data"`.

## Data-quality handling

- If `portfolio_decision_inputs` returns `data_quality.critical: true`, the portfolio-manager subagent forces `hold` on the affected tickers. Surface the warnings in the Risk notes section — do not swallow them.
- If every ticker has `hold` due to data gaps, prepend: `⚠️ All trades held due to data unavailability. Only AAPL, GOOGL, MSFT, NVDA, TSLA work without FINANCIAL_DATASETS_API_KEY.`

## What `/hedge-fund-trade` is NOT

- Not a real broker integration. The decisions are produced for review — the user executes them manually (or wires their own broker).
- Not stateful across sessions. Every invocation takes its portfolio state from `--cash` and `--positions` flags, uses defaults otherwise, and does not persist results.
- Not a replacement for `/hedge-fund`. Use `/hedge-fund` for "what do the analysts think?"; use `/hedge-fund-trade` for "what should I do?" with a specific portfolio state.
