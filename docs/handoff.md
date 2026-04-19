# Session Handoff — ai-hedgefund

## 1. Snapshot Timestamp

2026-04-20 (session continued from 2026-04-19)

## 2. Current Phase / Step

**Native-layer conversion, investor-personality batch — complete.**  13/19 v1 agents converted to Claude Code subagents + MCP tools. The remaining 6 agents (4 quant analysts + risk/portfolio managers) and one partially-started Technical Analyst are the next step.

Partial in-progress: Technical Analyst conversion. `src/agents/technical_analyst_analysis.py` (299 lines) exists locally uncommitted, and `mcp_server/server.py` has an unfinished import block for it (no `@mcp.tool()` wrapper yet). Either finish it or revert before starting a new batch.

## 3. Last Commit

`6f83ad8` `fix: close code-review findings across 3 analyzers + yfinance adapter (#6)` — branch `main`, in sync with `origin/main`.

**Uncommitted changes (intentional, per user):**
- `M  mcp_server/server.py` — adds import of `technical_analyst_analysis` symbols. Import is live but no `technical_analyst_analysis` MCP tool defined yet → server currently fails to start unless the import is valid. Important.
- `??  src/agents/technical_analyst_analysis.py` — 299 lines, six analyzers + weights. Important.

## 4. Active Thread

- **Just finished:** Code-review round 2 (PR #6 merged). Closed 2 critical silent bugs (Damodaran `ebit`/`interest_expense` from wrong Pydantic model; Burry `ev_to_ebit` non-existent field → fell back to `enterprise_value_to_ebitda_ratio`) + 1 Taleb v1-parity drift (removed `pre_signal`) + 1 slash-command wording. Audited 11 other `_analysis.py` modules clean.
- **Starting next:** either (a) finish Technical Analyst tool + subagent + parity review, or (b) start the remaining quant batch (valuation, sentiment, fundamentals) + Risk Manager + Portfolio Manager.
- **Pending user test:** `/hedge-fund TSLA` post-restart to verify today-date default and updated subagent prompts work end-to-end.

## 5. Pending User Decisions

- Whether to finish Technical Analyst (currently partial) before the quant batch, or after
- Whether Risk Manager / Portfolio Manager should reuse the same subagent+MCP pattern or get a different architecture (they produce position sizes / trade decisions, not bullish/bearish signals)
- Whether to add a beta data source for Damodaran (currently always NA — yfinance and financialdatasets.ai neither expose it in our schemas)

## 6. Recent Context (last 5 commits)

- `6f83ad8` fix: code-review round-2 — closed 2 silent FinancialMetrics/LineItem mismatches, Taleb v1-parity drift, stale slash-command wording; extended yfinance adapter with 7 new field mappings
- `a544f78` fix: Damodaran DCF — first of the silent `metrics.<rawfield>` bugs; introduced the audit pattern that found the others
- `ffdcdd4` fix: default end_date to today (not last month-end) — old defensive default became stale after `_resolve_market_cap` fix
- `f84dc9f` feat: add 6 more investors (Damodaran, Fisher, Pabrai, Jhunjhunwala, Druckenmiller, Taleb) — completes the 13-investor personality set
- `2281a13` feat: add 5 more investors (Munger, Burry, Wood, Ackman, Lynch) — validated the parallel-dispatch + parity-review pattern

## 7. Open Issues to Watch

- **Beta data missing** — Damodaran risk score effectively capped at 2/3 (beta check always NA). yfinance `.info` has `beta` but we don't expose it on `FinancialMetrics`; would need either a schema extension or a side-channel fetch. See `src/agents/aswath_damodaran_analysis.py:78`.
- **AAPL interest_expense NA on yfinance** — Damodaran interest-coverage check NA for AAPL specifically (NVDA works, returns 691.4x). yfinance doesn't populate the field consistently across tickers.
- **v1 parent files have inherited silent bugs** — `src/agents/aswath_damodaran.py`, `src/agents/michael_burry.py`, `src/agents/nassim_taleb.py` still contain the `metrics.<rawfield>` / `ev_to_ebit` / 0.7-0.3 drifts. Intentional per CLAUDE.md "don't edit v1 files." v1 LangGraph path remains buggy.
- **yfinance `_LINE_ITEM_SOURCES` is best-effort** — silent `None` for any canonical field not in the dict. Caught downstream by `data_quality` guardrail, but adding a new investor analyzer that requests an unknown field will degrade silently. See `src/tools/api_yfinance.py:32`.
- **Technical Analyst is half-wired** — see Section 3. Start next session by deciding finish-vs-revert.
- **MCP server process caches the old code** — Claude Code must be fully restarted for MCP server changes (`mcp_server/server.py`, `.env` DATA_SOURCE, subagent `.md` prompts) to take effect. `/reload-plugins` is NOT enough.

## 8. Environment State

- **Python**: 3.13 (project pinned `^3.11`; works on 3.13)
- **OS**: Windows 11, project at `D:\Claude Project\ai-hedgefund`
- **Data source**: `DATA_SOURCE=yfinance` active in `.env` (free, no key, supports `.KS`/`.KQ` etc.)
- **MCP servers active**: `hedgefund` (19 tools: 6 raw + 13 investor — `buffett`, `graham`, `munger`, `burry`, `ackman`, `wood`, `lynch`, `damodaran`, `fisher`, `pabrai`, `jhunjhunwala`, `druckenmiller`, `taleb`)
- **Claude Code plugins installed (project-scoped)**: `code-review@claude-plugins-official`
- **Secrets in `.env`**: `DATA_SOURCE` (not a secret); `FINANCIAL_DATASETS_API_KEY` not set (yfinance doesn't need it)
- **Git remotes**: `origin` → Jaclyn6/ai-hedge-fund (fork, push target); `upstream` → virattt/ai-hedge-fund (original, pull-only)
- **Branch**: `main`, up-to-date with `origin/main`
- **Session worktrees**: `.claude/worktrees/` gitignored; do NOT spawn — work in main project dir per feedback memory

## 9. How to Resume

1. Read `CLAUDE.md` to understand the Claude Code Native Layer architecture and the "Operating instructions" section (end_date defaulting, subagent invocation, parity-review skill).
2. Decide Technical Analyst disposition: either finish the MCP tool + subagent + run `review-investor-agent` skill, or `git checkout -- mcp_server/server.py && rm src/agents/technical_analyst_analysis.py` and start the full quant batch fresh.
3. Next concrete action: run `/hedge-fund TSLA` from a restarted Claude Code session to confirm today-date default + 13 investor dispatch works; if green, launch the 4 parallel conversion agents for the remaining quant analysts (pattern proven across PRs #2/#3).
