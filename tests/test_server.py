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
            },
        )

    def test_root_server_remains_compatible(self):
        self.assertIs(compatibility_mcp, mcp)

    def test_cli_defaults_to_stdio(self):
        args = _parser().parse_args([])
        self.assertEqual(args.transport, "stdio")


if __name__ == "__main__":
    unittest.main()
