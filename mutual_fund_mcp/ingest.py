"""Refresh official PPFAS snapshots from the operator CLI."""

import argparse
import json

from clients.ppfas import FUNDS
from mutual_fund_mcp.server import holdings_service
from services.errors import FundError


def main():
    parser = argparse.ArgumentParser(
        description="Download and persist official PPFAS monthly holdings"
    )
    parser.add_argument("--month", required=True, help="YYYY-MM")
    parser.add_argument("--scheme-code", choices=sorted(FUNDS), action="append")
    args = parser.parse_args()
    results = []
    failed = False
    for code in args.scheme_code or FUNDS:
        try:
            snapshot = holdings_service._snapshot(code, args.month, refresh=True)
            results.append(
                {
                    "scheme_code": code,
                    "portfolio_date": snapshot["portfolio_date"],
                    "holdings": len(snapshot["holdings"]),
                    "source": snapshot["source"],
                }
            )
        except FundError as error:
            failed = True
            results.append({"scheme_code": code, **error.as_response()})
    print(json.dumps(results, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
