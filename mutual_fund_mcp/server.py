from __future__ import annotations

import argparse
import logging
import os
import time
from collections.abc import Callable, Sequence
from typing import Any

from fastmcp import FastMCP

from clients.amfi import AMFIProvider
from clients.mfapi import MFAPIProvider
from services.errors import FundError
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
        logger.exception("tool_call_failed tool=%s code=INTERNAL_ERROR", operation.__name__)
        return FundError("INTERNAL_ERROR", "An unexpected internal error occurred.").as_response()


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
    """Compare deterministic metrics for 2-10 exact scheme codes over one period."""
    return _call(service.compare_funds, scheme_codes, from_date, to_date)


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
