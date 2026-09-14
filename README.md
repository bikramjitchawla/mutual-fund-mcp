# Mutual Fund MCP

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/bikramjitchawla/mutual-fund-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/bikramjitchawla/mutual-fund-mcp/actions/workflows/ci.yml)

A Model Context Protocol server for Indian mutual-fund NAV data, deterministic analytics, benchmark comparison, and public portfolio research. It works with Claude Desktop, Cursor-style MCP clients, custom agents, and remote Streamable HTTP clients.

It provides:

- Fund-name search and exact scheme resolution
- Latest end-of-day NAV
- Historical NAV observations
- Absolute return, CAGR, annualized volatility, and maximum drawdown
- Side-by-side comparison of 2–10 funds, including rolling returns, downside risk, and recovery
- Monthly SIP simulation, XIRR, and SIP comparison across 2–10 funds
- Total-return benchmark comparison and standalone rolling-return analysis
- Public PPFAS holdings lookup and monthly ownership changes with explicit coverage
- Structured errors, source attribution, and freshness dates

NAV and benchmark analytics remain stateless. Holdings snapshots use a local SQLite database created on demand. There is no scheduled ingestion, RAG, or embedding layer. Missing market dates are never fabricated.

> This is a factual research tool, not an investment adviser. Past performance does not guarantee future results.

## Fastest local setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), clone this repository, and run:

```bash
make install
make install-claude
```

Fully quit and reopen Claude Desktop. The server appears under **Settings → Developer**, and its eighteen tools appear in **Search and tools**.

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
| `compare_funds` | Compare 2–10 schemes: return, risk, rolling returns, drawdown duration, and recovery |
| `calculate_sip_returns` | Simulate monthly SIP contributions and calculate units, value, profit, and XIRR |
| `compare_sip_returns` | Compare monthly SIP outcomes across 2–10 schemes |
| `calculate_rolling_returns` | Return 1Y/3Y rolling windows and summary statistics |
| `search_benchmarks` | List supported total-return indices |
| `compare_fund_with_benchmark` | Compare fund and benchmark on common dates |
| `get_holdings_coverage` | List supported PPFAS schemes and disclosure months |
| `get_fund_holdings` | Retrieve a covered fund's monthly ISIN holdings |
| `get_funds_holding_stock` | Rank covered funds holding an ISIN by reported weight |
| `compare_fund_overlap` | Summarize weighted overlap, top shared securities, and key differences across covered funds |
| `get_stock_ownership_changes` | Compare positions across matched monthly snapshots |
| `get_funds_accumulating_stock` | Find quantity increases since the preceding month |
| `get_new_fund_buyers` | Find newly present positions in matched snapshots |
| `get_fund_exits_from_stock` | Find positions absent from the next matched snapshot |

Dates use `YYYY-MM-DD`. Historical requests are limited to five years. Metrics use the first and last available observations inside the requested range. Volatility is the sample standard deviation of successive NAV returns, annualized with `sqrt(252)`.

## Advanced fund comparison

`compare_funds(scheme_codes, from_date, to_date)` keeps its existing signature and
response fields, including `volatility_pct`. Each fund now also includes
`annualized_volatility_pct`, `downside_volatility_pct`, `calmar_ratio`,
`sortino_ratio`, `rolling_returns`, `max_drawdown_duration_days`, and `recovery_days`.
Calculations remain deterministic Python and use only NAVs within the requested period.

- **Rolling returns:** For each available starting NAV, find the first observation
  on or after its 1-year or 3-year calendar anniversary (February 29 clamps to
  February 28 when needed). Both periods report annualized returns using actual
  elapsed days and 365.2425 days/year. `rolling_returns["1y"]` and `["3y"]` contain
  `count`, `average_pct`, `best_pct`, and `worst_pct`. Incomplete windows are excluded;
  no complete windows means count zero and null summaries. No NAVs are interpolated.
  Missing observations can lengthen a window beyond its anniversary.
- **Downside volatility:** Square negative successive NAV returns (replace positive
  returns with zero), average over **all** returns, then take the square root and
  annualize with `sqrt(252)`. Like existing volatility, this treats successive
  observations as trading-day returns; sparse history can distort the estimate.
- **Sortino:** CAGR divided by annualized downside volatility, with a fixed zero
  minimum acceptable return. **Calmar:** CAGR divided by the absolute maximum
  drawdown over the same observation period. A zero denominator produces null.
  Ratios use unrounded inputs. No risk-free-rate source or Sharpe ratio is introduced.
- **Drawdown duration:** Longest calendar-day span from the prior peak to recovery
  at or above that peak. An ongoing episode runs through the last observation.
  No drawdown produces zero days.
- **Recovery:** Calendar days from the trough of the first deepest drawdown to
  recovery of its prior peak. An unrecovered drawdown or no drawdown produces null.
  This need not belong to the longest drawdown episode.

The response includes `advanced_metrics_method` with these conventions. Each
fund retains its actual `observation_from` and `observation_to`; comparisons do
not force a shared observation calendar. `data_as_of` is the earliest last
observation across the funds. Different histories may yield different rolling
window counts, so compare coverage alongside results.

Example MCP arguments:

```json
{
  "scheme_codes": ["120503", "122639"],
  "from_date": "2021-01-01",
  "to_date": "2026-01-01"
}
```

## Monthly SIP and XIRR

Use `calculate_sip_returns(scheme_code, monthly_amount, from_date, to_date)`
for one fund, or `compare_sip_returns(scheme_codes, monthly_amount, from_date, to_date)`
for 2–10 distinct funds. The amount must be finite and positive; the start must
precede the end, and the existing five-year range limit applies.

```json
{
  "scheme_code": "120503",
  "monthly_amount": 10000,
  "from_date": "2021-01-01",
  "to_date": "2026-01-01"
}
```

This schedules 60 installments. Monthly dates start at `from_date` inclusive
and stop before `to_date`. Each month uses the original start day, clamped to
that month's last day: a January 31 start schedules February 28/29 and March 31.
Each purchase uses the first NAV on or after its scheduled date, up to `to_date`.
Multiple delayed installments can therefore execute on the same observed date.
No missing NAVs are interpolated.

The result includes `installments`, `total_invested`, `total_units`, `ending_nav`,
`current_value`, `profit`, `absolute_gain_pct`, and `xirr_pct`. `installment_details`
exposes each scheduled date, actual investment date, amount, NAV, and units.
Units are summed without intermediate rounding and valued using the last NAV
on or before `to_date`. Amounts are reported to two decimals, aggregate units
to eight, and percentage returns to four; calculations use unrounded values.
No taxes, exit loads, or transaction charges are modeled.

XIRR uses negative contributions on **actual investment dates** and one positive
terminal portfolio value. It solves the dated cash-flow equation with ACT/365
(year fractions are elapsed calendar days divided by 365), using a deterministic
bisection in log-rate space. `xirr_pct` is null when no holding time exists or a
rate cannot be represented within the solver's log-rate bounds of -700 to 700;
`xirr_status` distinguishes this from a calculated zero return.

When the provider's final observation predates a scheduled installment,
that installment has no executable NAV. It appears in `unfilled_installment_dates`
and is excluded from invested capital. `scheduled_installments` includes both
executed and unfilled dates. Empty history produces a structured `NO_NAV_DATA` error.

SIP comparison uses the same requested amount and schedule for all funds. Each
fund retains its own execution dates, installment count, valuation date, and
source metadata. Different data coverage may mean different invested totals;
compare these alongside XIRR. The comparison's `data_as_of` is the earliest final
observation across funds. Provider failures use the existing structured error
contract instead of silently omitting a fund.

## Benchmark and holdings setup

See [Benchmark and holdings intelligence](docs/intelligence.md) for usage,
calculation conventions, environment settings, persistence and source limitations.

Benchmark comparison uses NSE total-return indices, with an explicitly configured
CSV provider available when live data cannot be reached. Live NSE verification
was blocked by provider timeouts in the implementation environment.

Holdings lookup currently covers **four PPFAS schemes**, not the whole market.
The official monthly XLSX disclosures are validated and stored automatically on
first use. Responses expose source dates, coverage gaps and excluded asset types.
Historical quantity changes do not by themselves establish actual buying/selling.

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
