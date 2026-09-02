"""Minimal client for a locally or remotely running Mutual Fund MCP server."""

from __future__ import annotations

import argparse
import asyncio

from fastmcp import Client


async def call_server(endpoint: str) -> None:
    async with Client(endpoint) as client:
        tools = await client.list_tools()
        print("Tools:", ", ".join(tool.name for tool in tools))

        result = await client.call_tool(
            "get_latest_nav",
            {"scheme_code": "122639"},
        )
        print("Latest NAV:", result.data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "endpoint",
        nargs="?",
        default="http://127.0.0.1:8000/mcp/",
        help="Streamable HTTP MCP endpoint",
    )
    args = parser.parse_args()
    asyncio.run(call_server(args.endpoint))


if __name__ == "__main__":
    main()

