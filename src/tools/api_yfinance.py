"""yfinance adapter — mirrors `src.tools.api` signatures.

Activated by setting `DATA_SOURCE=yfinance` in the environment. Unlike
financialdatasets.ai, yfinance is completely free and has no ticker gating —
works on any Yahoo-listed security including Korean (suffix `.KS`/`.KQ`),
European, etc. Trade-off: Yahoo is an unofficial scraper, occasionally
breaks when Yahoo changes their page; the yfinance maintainers typically
patch within days.

Field coverage is best-effort: we fill every field our Buffett/Graham
analyzers actually read. Missing fields surface through the MCP server's
`data_quality` block and the PostToolUse hook.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import pandas as pd
import yfinance as yf

from src.data.models import (
    CompanyNews,
    FinancialMetrics,
    InsiderTrade,
    LineItem,
    Price,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Row-name lookup: canonical (our schema) → list of yfinance candidate labels.
# Probed in order; first hit wins.
# ──────────────────────────────────────────────────────────────────────────────
_LINE_ITEM_SOURCES: dict[str, list[tuple[str, list[str]]]] = {
    "net_income": [
        ("financials", ["Net Income", "Net Income Common Stockholders", "Net Income Continuous Operations"]),
    ],
    "capital_expenditure": [("cashflow", ["Capital Expenditure"])],
    "depreciation_and_amortization": [
        ("cashflow", ["Depreciation And Amortization", "Depreciation Amortization Depletion"]),
        ("financials", ["Reconciled Depreciation"]),
    ],
    "outstanding_shares": [
        ("balance_sheet", ["Ordinary Shares Number", "Share Issued"]),
    ],
    "total_assets": [("balance_sheet", ["Total Assets"])],
    "total_liabilities": [
        ("balance_sheet", ["Total Liabilities Net Minority Interest"]),
    ],
    "shareholders_equity": [
        ("balance_sheet", ["Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest"]),
    ],
    "dividends_and_other_cash_distributions": [
        ("cashflow", ["Cash Dividends Paid", "Common Stock Dividend Paid"]),
    ],
    "issuance_or_purchase_of_equity_shares": [
        ("cashflow", ["Net Common Stock Issuance", "Repurchase Of Capital Stock"]),
    ],
    "gross_profit": [("financials", ["Gross Profit"])],
    "revenue": [("financials", ["Total Revenue", "Operating Revenue"])],
    "free_cash_flow": [("cashflow", ["Free Cash Flow"])],
    "earnings_per_share": [("financials", ["Basic EPS", "Diluted EPS"])],
    "current_assets": [("balance_sheet", ["Current Assets"])],
    "current_liabilities": [("balance_sheet", ["Current Liabilities"])],
    # book_value_per_share is computed: shareholders_equity / outstanding_shares
}


def _safe(df, row_candidates: list[str], col) -> float | None:
    if df is None or df.empty:
        return None
    for name in row_candidates:
        if name in df.index:
            val = df.loc[name, col]
            if pd.notna(val):
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return None
    return None


def _yf_ticker(ticker: str, period: str):
    """Return (yf.Ticker, (financials_df, balance_sheet_df, cashflow_df)) matching the requested period."""
    t = yf.Ticker(ticker)
    if period == "annual":
        return t, (t.financials, t.balance_sheet, t.cashflow)
    # 'ttm' and 'quarterly' both use the quarterly statements as the base grid.
    return t, (t.quarterly_financials, t.quarterly_balance_sheet, t.quarterly_cashflow)


# ──────────────────────────────────────────────────────────────────────────────
# Prices
# ──────────────────────────────────────────────────────────────────────────────
def get_prices(ticker: str, start_date: str, end_date: str, api_key: str = None) -> list[Price]:
    t = yf.Ticker(ticker)
    # yfinance end is exclusive, so bump by 1 day to include end_date
    end_dt = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)
    df = t.history(start=start_date, end=end_dt.strftime("%Y-%m-%d"), interval="1d", auto_adjust=False)
    if df is None or df.empty:
        return []
    out: list[Price] = []
    for idx, row in df.iterrows():
        try:
            out.append(Price(
                open=float(row["Open"]),
                close=float(row["Close"]),
                high=float(row["High"]),
                low=float(row["Low"]),
                volume=int(row["Volume"]) if pd.notna(row["Volume"]) else 0,
                time=idx.strftime("%Y-%m-%d"),
            ))
        except (KeyError, ValueError, TypeError) as e:
            logger.debug("skipping row for %s: %s", ticker, e)
            continue
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Market cap
# ──────────────────────────────────────────────────────────────────────────────
def get_market_cap(ticker: str, end_date: str, api_key: str = None) -> float | None:
    t = yf.Ticker(ticker)
    # `info` reflects the CURRENT market cap. For historical end_dates, prefer
    # close_price_at_end_date × most-recent-reported-outstanding-shares so the
    # caller gets a point-in-time value consistent with the chosen date.
    info = t.info or {}
    today = datetime.now().strftime("%Y-%m-%d")

    if end_date >= today:
        mc = info.get("marketCap")
        return float(mc) if mc else None

    # Historical: close × shares
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = (end_dt - timedelta(days=15)).strftime("%Y-%m-%d")
    df = t.history(start=start_dt, end=(end_dt + timedelta(days=1)).strftime("%Y-%m-%d"), interval="1d", auto_adjust=False)
    if df is None or df.empty:
        mc = info.get("marketCap")
        return float(mc) if mc else None
    latest_close = float(df["Close"].iloc[-1])
    shares = info.get("sharesOutstanding")
    if not shares:
        bs = t.quarterly_balance_sheet
        shares = _safe(bs, ["Ordinary Shares Number", "Share Issued"], bs.columns[0]) if bs is not None and not bs.empty else None
    if not shares:
        return None
    return latest_close * float(shares)


# ──────────────────────────────────────────────────────────────────────────────
# Line items (the big one — both analyses lean on these)
# ──────────────────────────────────────────────────────────────────────────────
def search_line_items(
    ticker: str,
    line_items: list[str],
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[LineItem]:
    t, (fin, bs, cf) = _yf_ticker(ticker, period)
    info = t.info or {}
    currency = info.get("financialCurrency", "USD")

    # Intersect report periods with end_date (cols < end_date only).
    if fin is None or fin.empty:
        return []
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    cols_sorted = sorted([c for c in fin.columns if pd.Timestamp(c).to_pydatetime() <= end_dt], reverse=True)[:limit]

    def source_df(tag: str):
        return {"financials": fin, "balance_sheet": bs, "cashflow": cf}[tag]

    results: list[LineItem] = []
    for col in cols_sorted:
        extra: dict = {}
        for item_name in line_items:
            if item_name == "book_value_per_share":
                equity = _safe(bs, ["Stockholders Equity", "Common Stock Equity"], col)
                shares = _safe(bs, ["Ordinary Shares Number", "Share Issued"], col)
                extra[item_name] = (equity / shares) if (equity and shares) else None
                continue
            sources = _LINE_ITEM_SOURCES.get(item_name, [])
            value = None
            for tag, candidates in sources:
                df = source_df(tag)
                value = _safe(df, candidates, col)
                if value is not None:
                    break
            extra[item_name] = value

        report_period = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
        results.append(LineItem(ticker=ticker, report_period=report_period, period=period, currency=currency, **extra))

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Financial metrics
# ──────────────────────────────────────────────────────────────────────────────
def get_financial_metrics(
    ticker: str,
    end_date: str,
    period: str = "ttm",
    limit: int = 10,
    api_key: str = None,
) -> list[FinancialMetrics]:
    t, (fin, bs, cf) = _yf_ticker(ticker, period)
    info = t.info or {}
    currency = info.get("financialCurrency", "USD")

    if fin is None or fin.empty:
        return []
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    cols_sorted = sorted([c for c in fin.columns if pd.Timestamp(c).to_pydatetime() <= end_dt], reverse=True)[:limit]

    results: list[FinancialMetrics] = []
    for i, col in enumerate(cols_sorted):
        is_latest = i == 0

        revenue = _safe(fin, ["Total Revenue", "Operating Revenue"], col)
        gross_profit = _safe(fin, ["Gross Profit"], col)
        operating_income = _safe(fin, ["Operating Income", "EBIT", "Total Operating Income As Reported"], col)
        net_income = _safe(fin, ["Net Income", "Net Income Common Stockholders"], col)
        equity = _safe(bs, ["Stockholders Equity", "Common Stock Equity"], col)
        assets = _safe(bs, ["Total Assets"], col)
        cur_a = _safe(bs, ["Current Assets"], col)
        cur_l = _safe(bs, ["Current Liabilities"], col)
        total_liab = _safe(bs, ["Total Liabilities Net Minority Interest"], col)
        total_debt = _safe(bs, ["Total Debt"], col)
        eps = _safe(fin, ["Basic EPS", "Diluted EPS"], col)

        gross_margin = (gross_profit / revenue) if (gross_profit and revenue) else None
        operating_margin = (operating_income / revenue) if (operating_income and revenue) else None
        net_margin = (net_income / revenue) if (net_income and revenue) else None
        roe = (net_income / equity) if (net_income and equity) else None
        roa = (net_income / assets) if (net_income and assets) else None
        current_ratio = (cur_a / cur_l) if (cur_a and cur_l) else None
        debt_to_equity = (total_debt / equity) if (total_debt and equity) else None
        debt_to_assets = (total_liab / assets) if (total_liab and assets) else None
        asset_turnover = (revenue / assets) if (revenue and assets) else None

        report_period = col.strftime("%Y-%m-%d") if hasattr(col, "strftime") else str(col)
        mc = float(info["marketCap"]) if (is_latest and info.get("marketCap")) else None

        m = FinancialMetrics(
            ticker=ticker,
            report_period=report_period,
            period=period,
            currency=currency,
            market_cap=mc,
            enterprise_value=float(info["enterpriseValue"]) if (is_latest and info.get("enterpriseValue")) else None,
            price_to_earnings_ratio=float(info["trailingPE"]) if (is_latest and info.get("trailingPE")) else None,
            price_to_book_ratio=float(info["priceToBook"]) if (is_latest and info.get("priceToBook")) else None,
            price_to_sales_ratio=float(info.get("priceToSalesTrailing12Months")) if (is_latest and info.get("priceToSalesTrailing12Months")) else None,
            enterprise_value_to_ebitda_ratio=float(info["enterpriseToEbitda"]) if (is_latest and info.get("enterpriseToEbitda")) else None,
            enterprise_value_to_revenue_ratio=float(info["enterpriseToRevenue"]) if (is_latest and info.get("enterpriseToRevenue")) else None,
            free_cash_flow_yield=None,
            peg_ratio=float(info["pegRatio"]) if (is_latest and info.get("pegRatio")) else None,
            gross_margin=gross_margin,
            operating_margin=operating_margin,
            net_margin=net_margin,
            return_on_equity=roe,
            return_on_assets=roa,
            return_on_invested_capital=None,
            asset_turnover=asset_turnover,
            inventory_turnover=None,
            receivables_turnover=None,
            days_sales_outstanding=None,
            operating_cycle=None,
            working_capital_turnover=None,
            current_ratio=current_ratio,
            quick_ratio=float(info["quickRatio"]) if (is_latest and info.get("quickRatio")) else None,
            cash_ratio=None,
            operating_cash_flow_ratio=None,
            debt_to_equity=debt_to_equity,
            debt_to_assets=debt_to_assets,
            interest_coverage=None,
            revenue_growth=float(info["revenueGrowth"]) if (is_latest and info.get("revenueGrowth")) else None,
            earnings_growth=float(info["earningsGrowth"]) if (is_latest and info.get("earningsGrowth")) else None,
            book_value_growth=None,
            earnings_per_share_growth=None,
            free_cash_flow_growth=None,
            operating_income_growth=None,
            ebitda_growth=None,
            payout_ratio=float(info["payoutRatio"]) if (is_latest and info.get("payoutRatio")) else None,
            earnings_per_share=eps,
            book_value_per_share=float(info["bookValue"]) if (is_latest and info.get("bookValue")) else None,
            free_cash_flow_per_share=None,
        )
        results.append(m)

    return results


# ──────────────────────────────────────────────────────────────────────────────
# Insider trades + news — best-effort. yfinance exposes limited data here.
# ──────────────────────────────────────────────────────────────────────────────
def get_insider_trades(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str = None,
) -> list[InsiderTrade]:
    t = yf.Ticker(ticker)
    try:
        df = t.insider_transactions
    except Exception:
        return []
    if df is None or df.empty:
        return []
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None

    out: list[InsiderTrade] = []
    for _, row in df.iterrows():
        try:
            start_date_val = row.get("Start Date")
            filing_dt = pd.Timestamp(start_date_val).to_pydatetime() if pd.notna(start_date_val) else None
            if filing_dt and filing_dt > end_dt:
                continue
            if start_dt and filing_dt and filing_dt < start_dt:
                continue
            out.append(InsiderTrade(
                ticker=ticker,
                issuer=None,
                name=str(row.get("Insider", "")) or None,
                title=str(row.get("Position", "")) or None,
                is_board_director=None,
                transaction_date=filing_dt.strftime("%Y-%m-%d") if filing_dt else None,
                transaction_shares=float(row["Shares"]) if pd.notna(row.get("Shares")) else None,
                transaction_price_per_share=None,
                transaction_value=float(row["Value"]) if pd.notna(row.get("Value")) else None,
                shares_owned_before_transaction=None,
                shares_owned_after_transaction=None,
                security_title=None,
                filing_date=filing_dt.strftime("%Y-%m-%d") if filing_dt else end_date,
            ))
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out


def get_company_news(
    ticker: str,
    end_date: str,
    start_date: str | None = None,
    limit: int = 1000,
    api_key: str = None,
) -> list[CompanyNews]:
    t = yf.Ticker(ticker)
    try:
        news_list = t.news or []
    except Exception:
        return []
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    start_dt = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None

    out: list[CompanyNews] = []
    for item in news_list[:limit]:
        try:
            # yfinance news item structure varies; be defensive
            content = item.get("content") if isinstance(item, dict) else None
            base = content if isinstance(content, dict) else item
            title = base.get("title") or ""
            pub = base.get("pubDate") or base.get("providerPublishTime") or base.get("displayTime")
            if isinstance(pub, (int, float)):
                published = datetime.fromtimestamp(pub)
            elif isinstance(pub, str):
                published = datetime.fromisoformat(pub.replace("Z", "+00:00")).replace(tzinfo=None)
            else:
                published = datetime.now()
            if published > end_dt:
                continue
            if start_dt and published < start_dt:
                continue
            provider = base.get("provider") or {}
            source = provider.get("displayName") if isinstance(provider, dict) else "Yahoo Finance"
            url = (base.get("canonicalUrl") or {}).get("url") if isinstance(base.get("canonicalUrl"), dict) else base.get("link", "")

            out.append(CompanyNews(
                ticker=ticker,
                title=title,
                author=None,
                source=source or "Yahoo Finance",
                date=published.strftime("%Y-%m-%d"),
                url=url or "",
                sentiment=None,
            ))
        except Exception:
            continue
    return out
