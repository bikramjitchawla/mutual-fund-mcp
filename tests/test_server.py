import unittest

from mutual_fund_mcp.server import _parser, mcp
from server import mcp as compatibility_mcp


class ServerPackagingTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_public_tools_are_registered(self):
        tools = await mcp.get_tools()
        self.assertEqual(
            set(tools),
            {
                "search_funds",
                "get_latest_nav",
                "get_nav_history",
                "calculate_fund_metrics",
                "compare_funds",
                "calculate_sip_returns",
                "compare_sip_returns",
                "calculate_rolling_returns",
                "search_benchmarks",
                "compare_fund_with_benchmark",
                "get_holdings_coverage",
                "get_fund_holdings",
                "get_funds_holding_stock",
                "compare_fund_overlap",
                "get_stock_ownership_changes",
                "get_funds_accumulating_stock",
                "get_new_fund_buyers",
                "get_fund_exits_from_stock",
            },
        )

    def test_root_server_remains_compatible(self):
        self.assertIs(compatibility_mcp, mcp)

    def test_cli_defaults_to_stdio(self):
        args = _parser().parse_args([])
        self.assertEqual(args.transport, "stdio")


if __name__ == "__main__":
    unittest.main()


class IntelligenceToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_intelligence_tools_through_mcp(self):
        import importlib
        import json
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from fastmcp import Client

        from clients.benchmarks import CSVBenchmarkProvider
        from services.benchmarks import BenchmarkService
        from services.mutual_funds import MutualFundService
        from tests.test_holdings import ISIN, snapshot
        from tests.test_holdings import service as make_holdings
        from tests.test_mutual_funds import FakeProvider

        server = importlib.import_module("mutual_fund_mcp.server")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "NIFTY_50_TRI.csv").write_text(
                "date,value\n2024-01-02,100\n2024-12-31,110\n"
            )
            holdings = make_holdings(
                root,
                {
                    ("122639", month): snapshot("122639", month, quantity=q)
                    for month, q in [("2026-07", 100), ("2026-08", 110)]
                },
            )
            with (
                patch.object(server, "holdings_service", holdings),
                patch.object(
                    server,
                    "benchmark_service",
                    BenchmarkService(FakeProvider(), CSVBenchmarkProvider(directory)),
                ),
                patch.object(server, "service", MutualFundService(FakeProvider())),
            ):
                async with Client(server.mcp) as client:
                    cases = [
                        ("search_benchmarks", {}),
                        (
                            "compare_fund_with_benchmark",
                            {
                                "scheme_code": "1",
                                "benchmark_code": "NIFTY_50_TRI",
                                "from_date": "2024-01-01",
                                "to_date": "2024-12-31",
                            },
                        ),
                        (
                            "calculate_rolling_returns",
                            {
                                "scheme_code": "1",
                                "from_date": "2024-01-01",
                                "to_date": "2024-12-31",
                            },
                        ),
                        ("get_holdings_coverage", {}),
                        (
                            "get_fund_holdings",
                            {"scheme_code": "122639", "month": "2026-08"},
                        ),
                        ("get_funds_holding_stock", {"isin": ISIN, "month": "2026-08"}),
                        (
                            "get_stock_ownership_changes",
                            {
                                "isin": ISIN,
                                "from_month": "2026-07",
                                "to_month": "2026-08",
                            },
                        ),
                        (
                            "get_funds_accumulating_stock",
                            {"isin": ISIN, "month": "2026-08"},
                        ),
                        ("get_new_fund_buyers", {"isin": ISIN, "month": "2026-08"}),
                        (
                            "get_fund_exits_from_stock",
                            {"isin": ISIN, "month": "2026-08"},
                        ),
                    ]
                    for tool, arguments in cases:
                        with self.subTest(tool=tool):
                            result = await client.call_tool(tool, arguments)
                            self.assertFalse(result.is_error)
                            payload = json.loads(result.content[0].text)
                            self.assertNotEqual(payload.get("success"), False, payload)
                            json.dumps(payload, allow_nan=False)
                    result = await client.call_tool(
                        "get_fund_holdings", {"scheme_code": "118955"}
                    )
                    self.assertEqual(
                        json.loads(result.content[0].text)["error"]["code"],
                        "UNSUPPORTED_HOLDINGS_SCHEME",
                    )
