from __future__ import annotations

import argparse
import logging
import os
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from clients.amfi import AMFIProvider
from clients.benchmarks import CSVBenchmarkProvider, NSEBenchmarkProvider
from clients.mfapi import MFAPIProvider
from clients.ppfas import PPFASProvider
from services.benchmarks import BenchmarkService
from services.errors import FundError
from services.holdings import HoldingsService
from services.holdings_store import HoldingsStore
from services.mutual_funds import MutualFundService

logger = logging.getLogger("mutual_fund_mcp")
logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    logger.addHandler(handler)
logger.propagate = False

mcp = FastMCP(
    "mutual-fund-mcp",
    version="0.1.0",
    instructions=(
        "Fetch Indian mutual-fund NAV data and deterministic analytics. "
        "Search for a scheme before using its exact scheme code. Prefer Direct Growth "
        "when the user has not specified a plan, and always identify the selected plan."
    ),
)

provider = (
    AMFIProvider()
    if os.getenv("MF_PROVIDER", "mfapi").casefold() == "amfi"
    else MFAPIProvider()
)
service = MutualFundService(provider)
benchmark_service = BenchmarkService(
    provider,
    CSVBenchmarkProvider(os.environ["MF_BENCHMARK_CSV_DIR"])
    if os.getenv("MF_BENCHMARK_CSV_DIR")
    else NSEBenchmarkProvider(),
)
holdings_service = HoldingsService(
    PPFASProvider(),
    HoldingsStore(
        os.getenv(
            "MF_HOLDINGS_DB",
            str(Path.home() / ".local/share/mutual-fund-mcp/holdings.sqlite3"),
        )
    ),
)


def _call(operation: Callable[..., dict], *args: Any) -> dict:
    started = time.monotonic()
    logger.info("tool_call_started tool=%s", operation.__name__)
    try:
        result = operation(*args)
        logger.info(
            "tool_call_completed tool=%s duration_ms=%d",
            operation.__name__,
            round((time.monotonic() - started) * 1000),
        )
        return result
    except FundError as error:
        logger.warning(
            "tool_call_failed tool=%s code=%s duration_ms=%d",
            operation.__name__,
            error.code,
            round((time.monotonic() - started) * 1000),
        )
        return error.as_response()
    except Exception:
        logger.exception(
            "tool_call_failed tool=%s code=INTERNAL_ERROR", operation.__name__
        )
        return FundError(
            "INTERNAL_ERROR", "An unexpected internal error occurred."
        ).as_response()


@mcp.tool()
def search_funds(query: str) -> dict:
    """Search mutual fund schemes by name. Resolve a name before using other tools."""
    return _call(service.search_funds, query)


@mcp.tool()
def get_latest_nav(scheme_code: str) -> dict:
    """Return the latest published end-of-day NAV for an exact scheme code."""
    return _call(service.get_latest_nav, scheme_code)


@mcp.tool()
def get_nav_history(scheme_code: str, from_date: str, to_date: str) -> dict:
    """Return NAV history. Dates must be ISO YYYY-MM-DD and span at most five years."""
    return _call(service.get_nav_history, scheme_code, from_date, to_date)


@mcp.tool()
def calculate_fund_metrics(scheme_code: str, from_date: str, to_date: str) -> dict:
    """Calculate deterministic absolute return, CAGR, volatility, and drawdown."""
    return _call(service.calculate_fund_metrics, scheme_code, from_date, to_date)


@mcp.tool()
def compare_funds(scheme_codes: list[str], from_date: str, to_date: str) -> dict:
    """Compare return, downside risk, rolling 1Y/3Y returns, drawdown duration and recovery for 2-10 schemes."""
    return _call(service.compare_funds, scheme_codes, from_date, to_date)


@mcp.tool()
def calculate_sip_returns(
    scheme_code: str, monthly_amount: float, from_date: str, to_date: str
) -> dict:
    """Simulate monthly SIP over at most five years; return units, value and ACT/365 XIRR.

    Schedule starts at from_date (inclusive), ends before to_date, and clamps
    the original day to month end. Buy at the first NAV on/after each date;
    value at the last NAV on/before to_date. Amount must be positive.
    """
    return _call(
        service.calculate_sip_returns, scheme_code, monthly_amount, from_date, to_date
    )


@mcp.tool()
def compare_sip_returns(
    scheme_codes: list[str], monthly_amount: float, from_date: str, to_date: str
) -> dict:
    """Compare monthly SIP value and XIRR for 2-10 schemes over at most five years.

    Uses the same schedule as calculate_sip_returns. Each fund exposes its
    actual executed installments and valuation date; coverage may differ.
    """
    return _call(
        service.compare_sip_returns, scheme_codes, monthly_amount, from_date, to_date
    )


@mcp.tool()
def calculate_rolling_returns(scheme_code: str, from_date: str, to_date: str) -> dict:
    """Return calendar 1Y/3Y rolling CAGR windows and summaries over at most five years."""
    return _call(service.calculate_rolling_returns, scheme_code, from_date, to_date)


@mcp.tool()
def search_benchmarks(query: str = "") -> dict:
    """Find supported total-return benchmarks; empty query lists the catalog."""
    return _call(benchmark_service.search_benchmarks, query)


@mcp.tool()
def compare_fund_with_benchmark(
    scheme_code: str, benchmark_code: str, from_date: str, to_date: str
) -> dict:
    """Compare fund and TRI benchmark CAGR, risk and return correlation on identical dates."""
    return _call(
        benchmark_service.compare_fund_with_benchmark,
        scheme_code,
        benchmark_code,
        from_date,
        to_date,
    )


@mcp.tool()
def get_holdings_coverage() -> dict:
    """List supported PPFAS schemes and available monthly XLSX disclosures. Not all AMCs."""
    return _call(holdings_service.get_holdings_coverage)


@mcp.tool()
def get_fund_holdings(scheme_code: str, month: str | None = None) -> dict:
    """Get ISIN-bearing cash holdings for a covered PPFAS scheme. Month YYYY-MM; defaults to latest.

    Downloads and persists the official monthly snapshot on first use. Cash,
    derivatives and receivables are excluded; arbitrage cash legs are included.
    """
    return _call(holdings_service.get_fund_holdings, scheme_code, month)


@mcp.tool()
def get_funds_holding_stock(isin: str, month: str | None = None) -> dict:
    """Rank covered PPFAS funds by reported ISIN security weight. Not all AMCs.

    Always explain response coverage and portfolio date. Missing funds are
    explicitly reported; an empty result does not mean no Indian funds hold it.
    """
    return _call(holdings_service.get_funds_holding_stock, isin, month)


@mcp.tool()
def compare_fund_overlap(
    scheme_codes: list[str],
    month: str | None = None,
    max_common_items: int = 10,
    max_unique_items: int = 4,
    include_details: bool = False,
) -> dict:
    """Return a concise holdings-overlap comparison for 2-10 covered funds.

    Use exact codes from get_holdings_coverage. Month is YYYY-MM; omitted means
    the latest common disclosure month. The default response has ready-to-display
    summary_text with overlap level, top common holdings and key differences.
    It shows 10 common and 4 unique holdings by default; both limits accept 1-25.
    Set include_details=true for complete ISIN-level data. Includes stocks and
    other cash securities; not equity-only. Present summary_text concisely unless
    the user explicitly asks for details.
    """
    return _call(
        holdings_service.compare_fund_overlap,
        scheme_codes,
        month,
        max_common_items,
        max_unique_items,
        include_details,
    )


@mcp.tool()
def get_stock_ownership_changes(isin: str, from_month: str, to_month: str) -> dict:
    """Compare quantities across matched PPFAS monthly snapshots (YYYY-MM).

    Corporate actions can cause changes; these are not verified trades.
    """
    return _call(
        holdings_service.get_stock_ownership_changes, isin, from_month, to_month
    )


@mcp.tool()
def get_funds_accumulating_stock(isin: str, month: str) -> dict:
    """List covered funds with increased quantities since the prior month; not verified buying flows."""
    return _call(holdings_service.get_funds_accumulating_stock, isin, month)


@mcp.tool()
def get_new_fund_buyers(isin: str, month: str) -> dict:
    """List new positions within covered funds with both monthly snapshots available."""
    return _call(holdings_service.get_new_fund_buyers, isin, month)


@mcp.tool()
def get_fund_exits_from_stock(isin: str, month: str) -> dict:
    """List positions absent in the current snapshot but present in the prior matched month."""
    return _call(holdings_service.get_fund_exits_from_stock, isin, month)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Mutual Fund MCP server.")
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default=os.getenv("MCP_TRANSPORT", "stdio"),
        help="stdio for local clients; http for remote/network clients",
    )
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--path", default=os.getenv("MCP_PATH", "/mcp/"))
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default=os.getenv("LOG_LEVEL", "INFO").upper(),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(
            transport="http",
            host=args.host,
            port=args.port,
            path=args.path,
            stateless_http=True,
        )


if __name__ == "__main__":
    main()
