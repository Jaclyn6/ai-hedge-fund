---
description: Run the AI hedge fund on one or more tickers, collecting signals from every investor subagent in parallel and producing a multi-horizon (short/mid/long) recommendation per ticker.
argument-hint: TICKER[,TICKER...] [YYYY-MM-DD]
---

# /hedge-fund

Orchestrate the investor subagents for the tickers in `$ARGUMENTS` and produce a **multi-horizon recommendation** (short-term / mid-term / long-term) per ticker.

## Parsing arguments

`$ARGUMENTS` is a comma-separated list of tickers, optionally followed by a date in `YYYY-MM-DD` format.

Examples:
- `AAPL` → ticker `AAPL`, end_date today
- `AAPL,MSFT,NVDA` → three tickers, end_date today
- `AAPL 2025-03-31` → ticker `AAPL`, end_date `2025-03-31`
- `AAPL,MSFT 2024-12-31` → two tickers, end_date `2024-12-31`

If no date is given, default to **today's date** (`YYYY-MM-DD`). Do not ask the user. The MCP server's `_resolve_market_cap` helper computes a live market cap from the most recent trading day's close × outstanding shares.

## Horizon buckets

Each subagent is bucketed by its **natural investment horizon** (inferred from its persona). When aggregating, compute a separate consensus **per bucket** — not one global consensus. This lets a short-term trader and a long-term holder each read their own section.

| Horizon | Subagents |
|---|---|
| **단기 / Short (<3M)** | `stanley-druckenmiller`, `technical-analyst` |
| **중기 / Mid (3M–2Y)** | `michael-burry`, `cathie-wood`, `bill-ackman`, `peter-lynch`, `mohnish-pabrai` |
| **장기 / Long (>2Y)** | `warren-buffett`, `ben-graham`, `charlie-munger`, `aswath-damodaran`, `phil-fisher`, `rakesh-jhunjhunwala`, `nassim-taleb` |

Grow this table as new subagents are added to `.claude/agents/`. Every subagent MUST belong to exactly one bucket.

## Execution

For each ticker, dispatch **every** subagent below **in parallel**. Use a single message containing one Agent tool call per subagent per ticker — do not serialize.

Subagent roster (horizon in brackets):
- `warren-buffett` [long] — quality + moat + intrinsic value
- `ben-graham` [long] — margin of safety + Graham Number + balance sheet strength
- `charlie-munger` [long] — mental models, moat, predictability, fair price for wonderful businesses
- `michael-burry` [mid] — deep value, contrarian, FCF yield focus, catalyst-aware
- `cathie-wood` [mid] — disruptive innovation, 5-year growth horizon, high R&D intensity
- `bill-ackman` [mid] — activist, high-quality, concentrated bets with catalysts
- `peter-lynch` [mid] — GARP (growth at reasonable price), PEG ratio, ten-bagger hunting
- `aswath-damodaran` [long] — "Dean of Valuation," story + numbers + disciplined DCF with CAPM cost of equity
- `phil-fisher` [long] — meticulous growth + 15 Points, scuttlebutt-style deep quality research
- `mohnish-pabrai` [mid] — Dhandho, "heads I win / tails I don't lose much," low-risk doubles in 2-3Y
- `rakesh-jhunjhunwala` [long] — Big Bull of India, patient long-term growth conviction
- `stanley-druckenmiller` [short] — macro/momentum + asymmetric risk-reward setups
- `nassim-taleb` [long] — tail risk, antifragility, barbell strategy, Black Swan sentinel
- `technical-analyst` [short] — pure price/trend/momentum/RSI/vol/volume (no fundamentals)

For each subagent call, pass a prompt like:
```
Analyze {ticker} for end_date {end_date}. Return only the final JSON signal block, no prose.
```

## Aggregating signals per bucket

Parse each subagent's JSON output into `{investor, signal, confidence, reasoning}`. Group into the 3 buckets per the horizon-buckets table above.

**Important:** treat `unavailable` signals as "data gap" — do not count them in the consensus math but still list them in the per-bucket table so the user sees the gap.

For each bucket (ignoring `unavailable` votes), compute a **bucket signal** using these rules applied to that bucket only:

| Bucket consensus | Bucket signal | Action |
|---|---|---|
| All bullish | **strong buy** | buy |
| Majority bullish, none bearish | **buy** | buy |
| All bearish | **strong sell** | sell |
| Majority bearish, none bullish | **sell** | sell |
| Bullish and bearish mixed | **neutral** | hold |
| All neutral | **neutral** | hold |
| All `unavailable` | **unavailable** | — |

Bucket confidence = mean of that bucket's contributing confidences (excluding `unavailable`), rounded.

## Output format

Present one consolidated markdown report to the user. **Default to Korean** when the user's most recent message was in Korean; otherwise English. Structure per ticker:

```markdown
## Hedge Fund Analysis — {end_date}

### {TICKER}

**📊 종합 시간축별 판단 / Multi-Horizon View**

| 시간축 / Horizon | 시그널 / Signal | 확신도 / Confidence | 기여 에이전트 / Contributors |
|---|---|---|---|
| 단기 (<3M) | ... | ... | Druckenmiller, Technical Analyst |
| 중기 (3M~2Y) | ... | ... | Burry, Wood, Ackman, Lynch, Pabrai |
| 장기 (>2Y) | ... | ... | Buffett, Graham, Munger, Damodaran, Fisher, Jhunjhunwala, Taleb |

**📈 단기 / Short-term (<3M)**

| Investor | Signal | Confidence | Reasoning |
|---|---|---|---|
| Stanley Druckenmiller | ... | ... | ... |
| Technical Analyst | ... | ... | ... |

**버킷 합의 / Bucket consensus:** {signal} ({confidence}). {1-sentence consensus rationale.}

**📅 중기 / Mid-term (3M–2Y)**

| Investor | Signal | Confidence | Reasoning |
|---|---|---|---|
| Michael Burry | ... | ... | ... |
| Cathie Wood | ... | ... | ... |
| Bill Ackman | ... | ... | ... |
| Peter Lynch | ... | ... | ... |
| Mohnish Pabrai | ... | ... | ... |

**버킷 합의 / Bucket consensus:** {signal} ({confidence}). {rationale.}

**📆 장기 / Long-term (>2Y)**

| Investor | Signal | Confidence | Reasoning |
|---|---|---|---|
| Warren Buffett | ... | ... | ... |
| Ben Graham | ... | ... | ... |
| Charlie Munger | ... | ... | ... |
| Aswath Damodaran | ... | ... | ... |
| Phil Fisher | ... | ... | ... |
| Rakesh Jhunjhunwala | ... | ... | ... |
| Nassim Taleb | ... | ... | ... |

**버킷 합의 / Bucket consensus:** {signal} ({confidence}). {rationale.}

**🎯 Final Synthesis** — 1 paragraph explaining convergence/divergence across the 3 horizons. Example: "장기·중기 bearish지만 단기 bullish — 모멘텀·내부자 매수·긍정 뉴스 흐름이 단기에는 유효하지만, DCF 기반 밸류에이션 갭(-95%)이 2년 안에 닫힐 경우 하락 여지가 큼. 장기 홀딩이라면 매도, 1M 스윙이라면 흐름 활용 가능."

### {TICKER_2}

(same structure)
```

If multiple tickers: end with a portfolio summary line **using the long-term bucket as the default investment decision**:
`Portfolio summary (long-term basis): 1 buy (MSFT), 1 hold (AAPL), 0 sell.`

## Data-quality handling

- If a bucket has all `unavailable`: show the bucket signal as `unavailable` and the table rows with their `unavailable` markers. Do not fabricate.
- If every investor across all buckets returns neutral with confidence <40 due to insufficient data: prepend `⚠️ {TICKER}: financial data unavailable without FINANCIAL_DATASETS_API_KEY. Only AAPL, GOOGL, MSFT, NVDA, TSLA work on the free tier.`
- Never invent a signal. Surface the limitation.

## Final Synthesis guidance

The `🎯 Final Synthesis` paragraph is the most important part of the report. It should:
1. **Explicitly compare the 3 buckets** — do they agree or diverge?
2. **Name the timeframe for each recommendation** — e.g. "스윙 트레이더(1M)는 매수 가능, 2Y 이상 홀더는 매도."
3. **Explain WHY they diverge** — e.g. "단기 모멘텀이 장기 밸류에이션 수렴보다 먼저 반영됨" or "실적 재가속 기대가 단기에 선반영되나 DCF로는 정당화 안됨."
4. **Stay grounded in the evidence** — quote specific numbers from the subagent reports (returns, DCF gaps, DCF values, multiples).
