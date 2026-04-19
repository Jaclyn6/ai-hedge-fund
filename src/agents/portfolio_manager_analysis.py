"""Pure portfolio-manager helpers.

Deterministic pre-LLM math extracted from `src/agents/portfolio_manager.py`.
The Claude Code native layer calls these through an MCP tool and lets the
`portfolio-manager` subagent (i.e. Claude itself) do the final action/qty
selection — replacing the v1 LangChain `call_llm` step.
"""
from __future__ import annotations


def compute_allowed_actions(
    tickers: list[str],
    current_prices: dict[str, float],
    max_shares: dict[str, int],
    portfolio: dict,
) -> dict[str, dict[str, int]]:
    """Determine allowed actions + max qty per ticker given cash, positions, margin.

    Mirror of v1 `compute_allowed_actions`. Returns `{ticker: {action: qty}}`
    where `hold` is always present; other actions (`buy`, `sell`, `short`,
    `cover`) only appear when they have non-zero capacity.
    """
    allowed: dict[str, dict[str, int]] = {}
    cash = float(portfolio.get("cash", 0.0))
    positions = portfolio.get("positions", {}) or {}
    margin_requirement = float(portfolio.get("margin_requirement", 0.5))
    margin_used = float(portfolio.get("margin_used", 0.0))
    equity = float(portfolio.get("equity", cash))

    for ticker in tickers:
        price = float(current_prices.get(ticker, 0.0))
        pos = positions.get(
            ticker,
            {"long": 0, "long_cost_basis": 0.0, "short": 0, "short_cost_basis": 0.0},
        )
        long_shares = int(pos.get("long", 0) or 0)
        short_shares = int(pos.get("short", 0) or 0)
        max_qty = int(max_shares.get(ticker, 0) or 0)

        actions = {"buy": 0, "sell": 0, "short": 0, "cover": 0, "hold": 0}

        if long_shares > 0:
            actions["sell"] = long_shares
        if cash > 0 and price > 0:
            max_buy_cash = int(cash // price)
            max_buy = max(0, min(max_qty, max_buy_cash))
            if max_buy > 0:
                actions["buy"] = max_buy

        if short_shares > 0:
            actions["cover"] = short_shares
        if price > 0 and max_qty > 0:
            if margin_requirement <= 0.0:
                max_short = max_qty
            else:
                available_margin = max(0.0, (equity / margin_requirement) - margin_used)
                max_short_margin = int(available_margin // price)
                max_short = max(0, min(max_qty, max_short_margin))
            if max_short > 0:
                actions["short"] = max_short

        pruned = {"hold": 0}
        for k, v in actions.items():
            if k != "hold" and v > 0:
                pruned[k] = v

        allowed[ticker] = pruned

    return allowed


def compact_signals(signals_by_ticker: dict[str, dict]) -> dict[str, dict]:
    """Shrink full analyst-signal payloads to `{agent: {sig, conf}}` per ticker.

    Accepts either v1-style `{signal, confidence}` keys or native-layer's
    already-compacted `{sig, conf}` keys so the same helper works on both.
    """
    out: dict[str, dict] = {}
    for ticker, agents in signals_by_ticker.items():
        if not agents:
            out[ticker] = {}
            continue
        compact: dict[str, dict] = {}
        for agent, payload in agents.items():
            if not isinstance(payload, dict):
                continue
            sig = payload.get("sig") or payload.get("signal")
            conf = payload["conf"] if "conf" in payload else payload.get("confidence")
            if sig is not None and conf is not None:
                compact[agent] = {"sig": sig, "conf": conf}
        out[ticker] = compact
    return out


def max_shares_from_limits(
    position_limits: dict[str, float],
    current_prices: dict[str, float],
) -> dict[str, int]:
    """Convert {ticker: $limit} + {ticker: price} → {ticker: max_shares}."""
    out: dict[str, int] = {}
    for t, limit in position_limits.items():
        price = float(current_prices.get(t, 0.0))
        if price > 0:
            out[t] = int(float(limit) // price)
        else:
            out[t] = 0
    return out
