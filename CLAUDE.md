# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-powered hedge fund simulator (educational, does not place real trades). 19 agents — 13 famous-investor personalities (Buffett, Graham, Munger, Burry, etc.) plus 4 quantitative analysts (valuation, sentiment, fundamentals, technicals), a risk manager, and a portfolio manager — collaborate via a LangGraph DAG to produce buy/sell/short/cover decisions for a set of tickers.

## Runtime Requirements

- **Python 3.11** (pinned in `pyproject.toml` as `^3.11`). Python 3.13+ has known compatibility issues per `app/README.md` — use pyenv/conda if system Python is newer.
- **Poetry** for dependency management.
- **At least one LLM API key** in `.env` (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `DEEPSEEK_API_KEY`, `GOOGLE_API_KEY`, `XAI_API_KEY`, `MOONSHOT_API_KEY`, `GIGACHAT_API_KEY`, `OPENROUTER_API_KEY`, or Azure). Or pass `--ollama` to use local models.
- **`FINANCIAL_DATASETS_API_KEY`** for most tickers. AAPL, GOOGL, MSFT, NVDA, TSLA work without a key (free tier on `api.financialdatasets.ai`).

Copy `.env.example` → `.env` and fill in keys.

## Common Commands

```bash
# Install
poetry install

# CLI — run the hedge fund
poetry run python src/main.py --ticker AAPL,MSFT,NVDA
poetry run python src/main.py --ticker AAPL --ollama                       # local LLM
poetry run python src/main.py --ticker AAPL --start-date 2024-01-01 --end-date 2024-03-01
poetry run python src/main.py --ticker AAPL --show-reasoning               # show per-agent output
poetry run python src/main.py --ticker AAPL --analysts warren_buffett,ben_graham

# Backtester
poetry run python src/backtester.py --ticker AAPL,MSFT,NVDA

# Tests
poetry run pytest                                              # all
poetry run pytest tests/test_cache.py                          # one file
poetry run pytest tests/test_cache.py::test_name               # one test
poetry run pytest tests/backtesting/                           # subdirectory

# Web app (FastAPI backend + React/Vite frontend)
./app/run.sh        # mac/linux — one-shot setup + launch
app\run.bat         # windows
# Manual: `poetry run uvicorn main:app --reload` in app/backend, `npm run dev` in app/frontend
# Frontend: http://localhost:5173 — Backend: http://localhost:8000 — Docs: http://localhost:8000/docs

# Docker
cd docker && ./run.sh   # or run.bat on windows

# Formatting
poetry run black .
poetry run isort .
```

## Architecture

### Orchestration — LangGraph DAG (`src/main.py`, `src/graph/state.py`)

The system is built around a single `AgentState` TypedDict with three reducers:

```python
messages:  Annotated[Sequence[BaseMessage], operator.add]   # appended
data:      Annotated[dict, merge_dicts]                     # deep-merged
metadata:  Annotated[dict, merge_dicts]                     # deep-merged
```

`src/main.py:run_hedge_fund` builds the graph in `create_workflow` (line 100+): a `start_node` fans out to all selected analyst nodes in parallel, every analyst connects to `risk_management_agent`, which connects to `portfolio_management_agent`, which connects to `END`. `workflow.compile().invoke(state)` runs it.

Analyst selection is interactive (via `questionary`) when `--analysts` / `--analysts-all` isn't passed; see `src/cli/input.py` for flags and `src/agents/__init__.py` (or `src/utils/analysts.py`) for the registry that maps agent IDs to node functions.

### Agent Contract (`src/agents/*.py`)

Every investor agent follows the same shape — when adding a new one, mirror this:

1. Accept `state: AgentState`, extract `tickers`, `end_date`, and API keys via `get_api_key_from_state`.
2. Loop per ticker. Fetch via `src/tools/api.py` (`get_financial_metrics`, `search_line_items`, `get_market_cap`, `get_prices`).
3. Compute domain-specific scores (e.g. `warren_buffett.py` has 8 sub-analyzers: moat, owner earnings, intrinsic value, etc.). These are pure functions — they're the most valuable part of each agent and should be preserved on any refactor.
4. Call `call_llm(...)` with a `ChatPromptTemplate` and a Pydantic output schema (e.g. `WarrenBuffettSignal`) to produce a structured bullish/bearish/neutral signal with confidence and reasoning.
5. Write into `state["data"]["analyst_signals"][agent_id][ticker]` and append a `HumanMessage` with the JSON.

The downstream contract is: **signal ∈ {bullish, bearish, neutral}, confidence ∈ [0, 100], reasoning: str**.

### Risk & Portfolio (`src/agents/risk_manager.py`, `src/agents/portfolio_manager.py`)

- **Risk Manager** fetches recent prices, computes volatility, applies a risk budget to each ticker, and writes `current_prices` + `remaining_position_limit` per ticker into signals. This runs *after* all analysts so it sees their output.
- **Portfolio Manager** reads every entry in `analyst_signals`, compresses to `{signal, confidence}` pairs, and makes a single LLM call with the combined signal matrix + position limits → `PortfolioManagerOutput` (buy/sell/short/cover per ticker). There is no weighted-voting aggregator — the LLM does the aggregation.

### LLM Layer (`src/llm/models.py`)

Facade is `get_model(model_name, model_provider, api_keys)` (~line 142). Provider enum covers 14 options; each branch constructs the matching LangChain chat class (`ChatOpenAI`, `ChatAnthropic`, `ChatGroq`, `ChatOllama`, etc.) with its API key. Models are listed in a JSON config loaded at line ~106. This layer is tightly coupled to LangChain — swapping to a non-LangChain client means rewriting `call_llm` and every agent's invocation site.

### Data Layer (`src/tools/api.py`)

Wraps `api.financialdatasets.ai` with a process-wide in-memory cache (`_cache`, line 26). Each function takes an `api_key` param that falls back to `FINANCIAL_DATASETS_API_KEY` env var. Rate limiting is tested in `tests/test_api_rate_limiting.py` — be careful modifying retry/backoff logic.

### Web App (`app/`)

- `app/backend/` — FastAPI server. Entry: `app/backend/main.py`. Uses SQLAlchemy + Alembic (see `app/backend/alembic/`). `POST /hedge-fund/run` is the main endpoint; it invokes the same `run_hedge_fund` from `src/main.py`.
- `app/frontend/` — React + Vite + TypeScript + TailwindCSS. Uses pnpm *or* npm (both lockfiles present; don't commit changes to both).

### v2/ — Parked Quantitative Rebuild

`v2/` is a **work-in-progress** ground-up rewrite that replaces personality agents with a quant pipeline: `data → signals → features → portfolio → risk → execution`. It outputs `SignalResult.value ∈ [-1, +1]` instead of bullish/bearish strings, and introduces CPCV / PBO validation and transaction cost modeling. **It is not wired into `src/main.py`** — the CLI and web app still run the v1 personality system. Treat `v2/` as a separate codebase; don't couple v1 changes to it. See `v2/README.md` and `v2/models.py` for the intended data contracts.

## Claude Code Native Layer (WIP)

An alternative to the v1 LangGraph pipeline that runs **inside Claude Code** using subagents + an MCP server. No separate LLM API key is needed — the Claude Code subscription provides the reasoning.

**Pieces:**
- `mcp_server/server.py` — FastMCP server wrapping `src/tools/api.py` (financial data) and the pure analyzer modules. Exposes raw data tools (`fetch_prices`, `fetch_financial_metrics`, `fetch_market_cap`, `fetch_line_items`, `fetch_insider_trades`, `fetch_company_news`) plus per-investor consolidated analysis tools (`buffett_analysis`, `graham_analysis`).
- `.claude/agents/warren-buffett.md` — Buffett subagent (quality + moat + intrinsic value). Calls `mcp__hedgefund__buffett_analysis`, returns `{signal, confidence, reasoning}` JSON.
- `.claude/agents/ben-graham.md` — Graham subagent (margin of safety + Graham Number + balance-sheet strength). Calls `mcp__hedgefund__graham_analysis`, returns the same JSON shape.
- `.claude/commands/hedge-fund.md` — `/hedge-fund TICKER[,TICKER...] [YYYY-MM-DD]` slash command. Parses args, dispatches every investor subagent per ticker **in parallel** (one message, multiple Agent tool calls), aggregates signals into a consolidated markdown report per ticker.
- `.mcp.json` — registers the `hedgefund` MCP server with Claude Code (launched as `python -m mcp_server.server`).
- `src/agents/<investor>_analysis.py` — pure analyzer functions, no LangChain deps. Shared between the v1 LangGraph flow and the MCP server. When adding a new investor, extract analyzers here first.

**Install (Python ≥3.11 in current env):**
```bash
pip install mcp langchain langchain-core pandas pydantic python-dotenv requests scipy
# or: poetry install   (picks up mcp via pyproject.toml)
```

**Smoke test the server alone:**
```bash
python -m mcp_server.server   # should print no errors and wait on stdio
```

**Use in Claude Code:** restart Claude Code so `.mcp.json` is picked up, then invoke the subagent via the Agent tool with `subagent_type: warren-buffett` and a prompt like `"Analyze AAPL for end_date 2025-03-31"`. The subagent will call `mcp__hedgefund__buffett_analysis` internally and return a structured signal.

**Not yet built:** subagents for the other 17 investors, and a true portfolio-manager orchestrator that outputs `{action, quantity, confidence}` with risk-manager-derived position sizing (the v1 behavior). The current `/hedge-fund` command produces a consensus bullish/bearish/neutral recommendation per ticker but does not size positions. Adding more investors requires only a new `_analysis.py` module, a new MCP tool, a new `.claude/agents/<name>.md`, and adding the subagent name to the list in `.claude/commands/hedge-fund.md`.

### Operating instructions for Claude Code sessions

**User intent:** the user wants this project driven through the Claude Code native layer (MCP + subagents), *not* through the v1 `poetry run python src/main.py` CLI. Default to the native layer for any "analyze ticker X" / "what would Buffett think of Y" / "run the hedge fund" style request. Only fall back to the v1 CLI if the user explicitly asks for it or if the native layer is clearly inadequate for the request.

**Preferred entry point — `/hedge-fund`:** for any multi-investor analysis, invoke the `/hedge-fund TICKER[,TICKER...] [YYYY-MM-DD]` slash command. It dispatches every investor subagent in parallel and produces a consolidated report. Only call a single investor subagent directly when the user explicitly names that investor (e.g. "what would Graham think of AAPL?").

**How to invoke a single investor subagent:** call the Agent tool with `subagent_type: warren-buffett` or `ben-graham` and a prompt that names the ticker and (optionally) an `end_date`. If the user doesn't give a date, pass today's date in `YYYY-MM-DD` format — don't ask. Example: `"Analyze NVDA for end_date 2025-04-18. Return the structured JSON signal."`

**Parallelism:** when the user asks about multiple tickers, dispatch one `warren-buffett` subagent per ticker in a single message (multiple Agent tool blocks) so they run in parallel. Don't serialize.

**Tickers without a `FINANCIAL_DATASETS_API_KEY`:** AAPL, GOOGL, MSFT, NVDA, TSLA work on the free tier. Any other ticker will return empty data and the subagent will (correctly) produce `signal: "neutral"` with low confidence. If the user wants other tickers, tell them they need `FINANCIAL_DATASETS_API_KEY` in `.env` — or switch to the free `yfinance` backend (see below).

**Data source switcher** — set `DATA_SOURCE=yfinance` in `.env` (or the shell) to route all fetches through [src/tools/api_yfinance.py](src/tools/api_yfinance.py) instead of financialdatasets.ai. Pros: free, no API key, any Yahoo-listed ticker (including Korean `.KS`/`.KQ`). Cons: unofficial scraper, occasionally breaks for a few days when Yahoo changes pages. The switch happens at [src/tools/api.py](src/tools/api.py) module load via env check; all downstream consumers (MCP server, analyzers) pick up the active backend transparently. Default remains `financialdatasets`. Note: yfinance provides 5 quarters of quarterly history vs financialdatasets.ai's 10 TTM periods, so Buffett's DCF intrinsic value estimate differs between backends — score direction agrees but absolute IV values won't match. Graham's analysis matches across backends since it uses the latest period only.

**Data-quality guardrail (STRICT).** Every `buffett_analysis` / `graham_analysis` response carries a `data_quality` block: `{complete, critical, missing_fields, degraded_analyzers, warnings}`. The schema is populated by `_assess_data_quality()` in [mcp_server/server.py](mcp_server/server.py) which scans analyzer details for phrases like "Insufficient data," "not available," "Limited" etc. A PostToolUse hook at [.claude/hooks/data_quality_check.py](.claude/hooks/data_quality_check.py) is registered in [.claude/settings.json](.claude/settings.json) to fire on every `mcp__hedgefund__*` call — if `complete: false`, it injects an `additionalContext` system reminder forcing the subagent to (a) list the missing/degraded fields to the user BEFORE any signal, (b) cap confidence, and (c) on `critical: true` (valuation broken) refuse to produce bullish/bearish/neutral at all and return `signal: "unavailable"` instead. Both `.claude/agents/warren-buffett.md` and `ben-graham.md` also embed this rule in their prompts — defense in depth since subagents run in isolated contexts. The user treats outputs as real investment decisions; silent data gaps are forbidden. When adding analyzers that can degrade on missing data, extend `_DEGRADATION_MARKERS` in `mcp_server/server.py` so new phrases get detected.

**Market cap is live, not quarter-stale.** `_resolve_market_cap(ticker, end_date)` in [mcp_server/server.py](mcp_server/server.py) computes `latest_close × outstanding_shares` using the most recent trading day ≤ `end_date` (falling back to quarter-report market cap only if prices fail). This matters because the free-tier `/company/facts/` endpoint returns `null` for current-day market cap, and the `/financial-metrics/` fallback gives a value from the last quarterly report which can be ±10% stale against today's price (MSFT at one test drifted -12.5% between report date and now). The helper also handles a timezone quirk: the price endpoint's "today" lags the client clock by a day, so we always query prices with `end_date − 1 day` and a 15-day window to guarantee at least one trading day. The `fetch_market_cap` MCP tool, `buffett_analysis`, and `graham_analysis` all route through this helper — do not reintroduce direct calls to `get_market_cap`.

**When MCP connection fails:** if `mcp__hedgefund__*` tools aren't listed or return errors:
1. Check the `hedgefund` server status with the `/mcp` slash command.
2. Verify the Python that `.mcp.json` launches has the deps: `python -c "from mcp_server.server import mcp"` from the project root should succeed silently. If it fails with `ModuleNotFoundError`, install the missing package (`mcp`, `langchain-core`, `pandas`, `pydantic`, `python-dotenv`, `requests` are the minimal set).
3. Confirm `.mcp.json` is at the project root and the working directory when Claude Code started was this project.

**Do not edit `src/agents/warren_buffett.py` to "simplify" it for the native flow.** It is still used by the v1 LangGraph CLI. The native flow reads from `src/agents/warren_buffett_analysis.py` (pure analyzer module). Keep that separation — if you improve an analyzer, edit the `_analysis.py` module and both paths benefit.

**When adding a new investor subagent:** (a) if the agent's v1 file at `src/agents/<name>.py` contains pure analyzer functions mixed with LangChain glue, extract the pure functions to `src/agents/<name>_analysis.py` first (same pattern as Buffett). (b) Add a matching MCP tool to `mcp_server/server.py` that runs the analyzers and returns a consolidated dict. (c) Create `.claude/agents/<name>.md` with the investor's persona, decision rules, and the MCP tool name in the `tools:` frontmatter field. (d) **Always run the `review-investor-agent` skill** (at `.claude/skills/review-investor-agent/SKILL.md`) to parity-check the new subagent against the v1 system prompt — don't skip this. It catches drift in principles, signal rules, confidence tiers, reasoning style, few-shot examples, and output schema. (e) Add the subagent name to the investor list inside `.claude/commands/hedge-fund.md`.

## Key Files for Orientation

| Concern | File |
|---|---|
| CLI entry / graph construction | `src/main.py` |
| Backtester entry | `src/backtester.py` |
| State schema & reducers | `src/graph/state.py` |
| Agent template (most sophisticated) | `src/agents/warren_buffett.py` |
| Signal aggregation | `src/agents/portfolio_manager.py` |
| Position sizing / risk | `src/agents/risk_manager.py` |
| LLM provider switchboard | `src/llm/models.py` |
| Financial data client | `src/tools/api.py` |
| CLI flags | `src/cli/input.py` |
| Agent registry / analyst picker | `src/utils/analysts.py` |
