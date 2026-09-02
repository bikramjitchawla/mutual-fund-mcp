"""Compatibility entrypoint for clients configured with ``server.py:mcp``."""

from mutual_fund_mcp.server import main, mcp

__all__ = ["main", "mcp"]


if __name__ == "__main__":
    main()
