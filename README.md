# Mutual Fund MCP

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/bikramjitchawla/mutual-fund-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/bikramjitchawla/mutual-fund-mcp/actions/workflows/ci.yml)

A stateless Model Context Protocol server for Indian mutual-fund NAV data and deterministic analytics. It works with Claude Desktop, Cursor-style MCP clients, custom agents, and remote Streamable HTTP clients.

It provides:

- Fund-name search and exact scheme resolution
- Latest end-of-day NAV
- Historical NAV observations
- Absolute return, CAGR, annualized volatility, and maximum drawdown
- Side-by-side comparison of 2–10 funds
- Structured errors, source attribution, and freshness dates

There is no database, scheduled ingestion, RAG, or embedding layer. Missing market dates are never fabricated.

> This is a factual research tool, not an investment adviser. Past performance does not guarantee future results.

## Fastest local setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), clone this repository, and run:

```bash
make install
make install-claude
```

Fully quit and reopen Claude Desktop. The server appears under **Settings → Developer**, and its five tools appear in **Search and tools**.

Try this prompt:

> Search for Parag Parikh Flexi Cap Fund, select the Direct Growth plan, and show its latest NAV.

### Claude Desktop without cloning

After this repository is public, users with `uv` can paste the following into their Claude Desktop MCP configuration:

```json
{
  "mcpServers": {
    "mutual-fund-mcp": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/bikramjitchawla/mutual-fund-mcp.git@v0.1.0",
        "mutual-fund-mcp"
      ],
      "env": {
        "MF_PROVIDER": "mfapi"
      }
    }
  }
}
```

On macOS, Claude stores this file at:

```text
~/Library/Application Support/Claude/claude_desktop_config.json
```

The same `mcpServers` object works with many MCP-compatible clients. A ready-to-copy version is available in [`examples/mcp-config.json`](examples/mcp-config.json).

## Command-line installation

Install from a checkout:

```bash
uv sync --extra dev
uv run mutual-fund-mcp --help
```

Or install directly from the public Git repository:

```bash
uvx --from git+https://github.com/bikramjitchawla/mutual-fund-mcp.git@v0.1.0 mutual-fund-mcp
```

The default transport is stdio, which is intended to be launched by an MCP client. It will wait silently when started manually.

## Run over HTTP

For custom agents or network clients:

```bash
uv run mutual-fund-mcp --transport http --host 127.0.0.1 --port 8000
```

The Streamable HTTP endpoint is:

```text
http://127.0.0.1:8000/mcp/
```

Call it with the included example:

```bash
uv run python examples/client.py
```

For a remote deployment, bind to `0.0.0.0`, place the service behind HTTPS, add authentication and rate limiting, and connect clients to `https://your-domain.example/mcp/`.

## Docker

Start a local HTTP server with:

```bash
docker compose up --build
```

Or build and run it directly:

```bash
docker build -t mutual-fund-mcp .
docker run --rm -p 8000:8000 mutual-fund-mcp
```

The image reads the platform-provided `PORT` environment variable, making it suitable for common container hosting platforms.

## Custom agent client

Any MCP-aware agent can use the HTTP endpoint. With FastMCP:

```python
from fastmcp import Client

client = Client("https://your-domain.example/mcp/")
```

The full executable example is in [`examples/client.py`](examples/client.py).

## Tools

| Tool | Purpose |
|---|---|
| `search_funds` | Resolve a fund name to exact scheme codes and plans |
| `get_latest_nav` | Fetch the latest published NAV |
| `get_nav_history` | Fetch normalized history over an ISO date range |
| `calculate_fund_metrics` | Calculate return, CAGR, volatility, and drawdown |
| `compare_funds` | Compare 2–10 schemes over one period |

Dates use `YYYY-MM-DD`. Historical requests are limited to five years. Metrics use the first and last available observations inside the requested range. Volatility is the sample standard deviation of successive NAV returns, annualized with `sqrt(252)`.

## Providers

The default provider is the scheme-specific JSON API at MFAPI.in, which makes interactive multi-year comparisons practical:

```bash
MF_PROVIDER=mfapi mutual-fund-mcp
```

A direct AMFI provider is included as an alternative. It uses AMFI's official text feeds and splits history into AMFI's 90-day maximum windows:

```bash
MF_PROVIDER=amfi mutual-fund-mcp
```

## Development

```bash
make install
make test
```

MCP tool failures use a structured contract:

```json
{
  "success": false,
  "error": {
    "code": "SCHEME_NOT_FOUND",
    "message": "No scheme matched the supplied scheme code."
  }
}
```

The clients use TLS verification, fixed provider URLs, bounded response sizes, timeouts, descriptive user agents, and bounded exponential-backoff retries. No arbitrary user-provided URL is accepted.

## Logs

Claude Desktop writes server logs on macOS to:

```bash
tail -F "$HOME/Library/Logs/Claude/mcp-server-mutual-fund-mcp.log"
```

The server logs tool names, completion times, and error codes without logging full NAV histories.
