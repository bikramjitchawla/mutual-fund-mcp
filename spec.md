Mutual Fund MCP

A lightweight, stateless Model Context Protocol (MCP) service for fetching Indian mutual fund data on demand and exposing deterministic analytics to Claude, Claude Desktop, or custom AI agents.

1. Goal

The MCP should:

Fetch mutual fund data only when requested.

Avoid a persistent database.

Avoid RAG, embeddings, and vector databases for numeric fund data.

Return structured JSON that an LLM can reason over.

Perform deterministic financial calculations in code rather than relying on the LLM for arithmetic.

Be usable from Claude Desktop or any MCP-compatible/custom tool client.

2. Architecture

User
  |
  v
Claude / Custom AI Agent
  |
  | MCP
  v
mutual-func-mcp
  |
  +--> Mutual Fund Data Provider
  |      |
  |      +--> AMFI
  |      +--> Optional JSON API provider
  |
  +--> Analytics Functions
         |
         +--> Absolute Return
         +--> CAGR
         +--> Volatility
         +--> Maximum Drawdown
         +--> Fund Comparison

There is intentionally no persistence layer.

NO PostgreSQL
NO SQLite
NO Redis
NO Vector DB
NO RAG
NO scheduled ingestion

3. Data Sources

Primary source: AMFI India

Use AMFI as the authoritative source wherever practical.

Useful data includes:

Scheme code

Scheme name

ISIN

Latest NAV

NAV date

Historical NAV

Scheme data

Fund performance information

Portfolio/risk disclosures when required in future versions

Official AMFI NAV page:

https://www.amfiindia.com/net-asset-value/nav-download

Important: AMFI historical NAV downloads may be limited to a maximum period per request, so the MCP implementation may need to split long historical requests into multiple calls.

Optional API layer

For a POC, a JSON-based public mutual fund API can simplify integration.

The provider should be abstracted behind a client so it can be changed without modifying MCP tool contracts.

Example:

Claude
   |
   v
MCP Tool
   |
   v
MutualFundClient
   |
   +--> AMFIClient
   |
   +--> OptionalApiClient

Do not make Claude dependent on a specific third-party API response format.

4. MCP Tool Design

Start with a small number of strongly defined tools.

search_funds

Search for matching schemes.

Input

{
  "query": "Parag Parikh Flexi Cap"
}

Output

{
  "results": [
    {
      "scheme_code": "122639",
      "scheme_name": "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
      "fund_house": "PPFAS Mutual Fund"
    }
  ]
}

get_latest_nav

Fetch the latest available NAV.

Input

{
  "scheme_code": "122639"
}

Output

{
  "scheme_code": "122639",
  "scheme_name": "Example Fund - Direct Growth",
  "nav": 100.25,
  "nav_date": "2026-09-01",
  "source": "AMFI"
}

The field should be called latest_nav or nav, not live_price.

Mutual funds generally publish end-of-day NAV values rather than continuously traded live prices.

get_nav_history

Fetch historical NAV values for a requested period.

Input

{
  "scheme_code": "122639",
  "from_date": "2021-09-01",
  "to_date": "2026-09-01"
}

Output

{
  "scheme_code": "122639",
  "from_date": "2021-09-01",
  "to_date": "2026-09-01",
  "data": [
    {
      "date": "2026-09-01",
      "nav": 100.25
    }
  ],
  "source": "AMFI"
}

The MCP should handle:

Non-business days

Missing NAV dates

Duplicate entries

Invalid scheme codes

Date-range validation

Provider request limits

calculate_fund_metrics

Calculate deterministic metrics from NAV history.

Input

{
  "scheme_code": "122639",
  "from_date": "2021-09-01",
  "to_date": "2026-09-01"
}

Output

{
  "scheme_code": "122639",
  "period": {
    "from": "2021-09-01",
    "to": "2026-09-01"
  },
  "metrics": {
    "absolute_return_pct": 81.42,
    "cagr_pct": 12.65,
    "annualized_volatility_pct": 15.32,
    "max_drawdown_pct": -22.17
  }
}

compare_funds

Compare multiple schemes over the same period.

Input

{
  "scheme_codes": [
    "122639",
    "119062"
  ],
  "from_date": "2021-09-01",
  "to_date": "2026-09-01"
}

Output

{
  "period": {
    "from": "2021-09-01",
    "to": "2026-09-01"
  },
  "funds": [
    {
      "scheme_code": "122639",
      "scheme_name": "Fund A",
      "cagr_pct": 14.2,
      "volatility_pct": 13.8,
      "max_drawdown_pct": -18.1
    },
    {
      "scheme_code": "119062",
      "scheme_name": "Fund B",
      "cagr_pct": 12.9,
      "volatility_pct": 16.4,
      "max_drawdown_pct": -24.7
    }
  ]
}

5. Recommended Analytics

The MCP should calculate numeric metrics itself.

Absolute Return

((ending_nav / starting_nav) - 1) * 100

CAGR

((ending_nav / starting_nav) ^ (1 / years) - 1) * 100

Daily Return

(nav_today / nav_previous) - 1

Annualized Volatility

For daily observations:

stddev(daily_returns) * sqrt(252)

This is an approximation and should be clearly labeled.

Maximum Drawdown

drawdown = (current_value - running_peak) / running_peak

Return the lowest drawdown observed in the selected interval.

6. Responsibilities

MCP Responsibilities

The MCP should:

Fetch current data.

Validate provider responses.

Normalize data.

Calculate deterministic metrics.

Return source information.

Return timestamps/dates.

Return errors explicitly.

Never fabricate missing financial data.

Claude Responsibilities

Claude should:

Understand the user's question.

Select the correct MCP tools.

Resolve fund names by calling search_funds.

Compare returned metrics.

Explain risk and performance.

Highlight limitations.

Generate natural-language analysis.

Claude should not invent NAVs, returns, AUM, holdings, expense ratios, or other financial values.

7. Example Claude Flow

User:

Compare Parag Parikh Flexi Cap and HDFC Flexi Cap over the last five years.
Tell me which had better returns and which was less volatile.

Claude:

search_funds("Parag Parikh Flexi Cap")
search_funds("HDFC Flexi Cap")

Then:

compare_funds(
    scheme_codes=[...],
    from_date=...,
    to_date=...
)

Claude receives structured metrics and produces the analysis.

8. Recommended Python Project Structure

mutual-func-mcp/
|
|-- server.py
|-- clients/
|   |-- __init__.py
|   |-- base.py
|   |-- amfi.py
|   `-- api_client.py
|
|-- services/
|   |-- __init__.py
|   |-- mutual_funds.py
|   `-- analytics.py
|
|-- models/
|   |-- __init__.py
|   `-- schemas.py
|
|-- tests/
|   |-- test_analytics.py
|   `-- test_mutual_funds.py
|
|-- requirements.txt
|-- pyproject.toml
`-- README.md

For an initial POC, this can be reduced to:

mutual-func-mcp/
|
|-- server.py
|-- mutual_funds.py
|-- analytics.py
`-- requirements.txt

9. FastMCP Server Skeleton

from fastmcp import FastMCP

from mutual_funds import (
    search_funds_from_provider,
    fetch_latest_nav,
    fetch_nav_history,
)

from analytics import calculate_metrics

mcp = FastMCP("mutual-func-mcp")


@mcp.tool()
def search_funds(query: str):
    return search_funds_from_provider(query)


@mcp.tool()
def get_latest_nav(scheme_code: str):
    return fetch_latest_nav(scheme_code)


@mcp.tool()
def get_nav_history(
    scheme_code: str,
    from_date: str,
    to_date: str,
):
    return fetch_nav_history(
        scheme_code=scheme_code,
        from_date=from_date,
        to_date=to_date,
    )


@mcp.tool()
def calculate_fund_metrics(
    scheme_code: str,
    from_date: str,
    to_date: str,
):
    history = fetch_nav_history(
        scheme_code=scheme_code,
        from_date=from_date,
        to_date=to_date,
    )

    return calculate_metrics(history)


if __name__ == "__main__":
    mcp.run()

10. Provider Client Pattern

Avoid putting provider-specific HTTP code directly inside MCP tools.

Use:

class MutualFundProvider:

    def search_funds(self, query: str):
        raise NotImplementedError

    def get_latest_nav(self, scheme_code: str):
        raise NotImplementedError

    def get_nav_history(
        self,
        scheme_code: str,
        from_date: str,
        to_date: str,
    ):
        raise NotImplementedError

Then implement:

class AMFIProvider(MutualFundProvider):
    ...

This makes it possible to change providers later without changing Claude's MCP contract.

11. Claude Desktop Integration

The exact command depends on the Python environment and transport used by the MCP server.

Example configuration:

{
  "mcpServers": {
    "mutual-func-mcp": {
      "command": "python",
      "args": [
        "/absolute/path/to/mutual-func-mcp/server.py"
      ]
    }
  }
}

If using uv:

{
  "mcpServers": {
    "mutual-func-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/mutual-func-mcp",
        "run",
        "server.py"
      ]
    }
  }
}

After Claude loads the server, tools should appear with names similar to:

search_funds
get_latest_nav
get_nav_history
calculate_fund_metrics
compare_funds

12. Custom Tool Integration

The same service can be exposed to another agent framework.

The important part is keeping the business interface independent from MCP.

                        +--> MCP / Claude
                        |
Mutual Fund Service ----+
                        |
                        +--> REST API
                        |
                        +--> LangGraph Agent
                        |
                        +--> Custom Python Agent

For example, keep this reusable:

service.search_funds(...)
service.get_latest_nav(...)
service.get_nav_history(...)
service.calculate_metrics(...)

Then the MCP layer only wraps those functions.

13. Suggested Agent Instructions

When this MCP is attached to an AI agent, use instructions similar to:

You have access to tools that fetch Indian mutual fund information.

When the user asks about a particular mutual fund:

1. Search for the scheme instead of guessing its scheme code.
2. Prefer Direct Growth plans when the user has not explicitly requested Regular or IDCW, but clearly state which plan is being analyzed.
3. Fetch current or historical data using the mutual fund tools.
4. Never invent NAV, performance, expense ratio, holdings, AUM, or other financial values.
5. Use tool-provided calculations where available.
6. Clearly state the date range used for every performance comparison.
7. Do not treat past performance as a guarantee of future returns.
8. Distinguish factual analysis from investment recommendations.
9. If data is unavailable, say so instead of estimating it.
10. Always identify the exact scheme/plan analyzed.

14. Error Contract

Errors should be structured.

Example:

{
  "success": false,
  "error": {
    "code": "SCHEME_NOT_FOUND",
    "message": "No mutual fund scheme matched the supplied scheme code."
  }
}

Suggested error codes:

SCHEME_NOT_FOUND
AMBIGUOUS_SCHEME
INVALID_DATE_RANGE
PROVIDER_UNAVAILABLE
RATE_LIMITED
NO_NAV_DATA
INVALID_PROVIDER_RESPONSE
CALCULATION_ERROR

15. HTTP Requirements

Use:

Request timeout

Retry with exponential backoff

User-Agent header

Strict response validation

TLS certificate validation

Rate-limit protection

Do not retry indefinitely.

Example:

timeout = 10
max_retries = 3

16. Caching

A database is not required.

For a POC, start with no cache.

If repeated provider calls become a problem, use a short-lived in-memory cache:

latest NAV       -> 5-30 minutes
scheme metadata  -> several hours
historical NAV   -> several hours

This remains stateless from a persistence perspective and can be removed at any time.

17. Data Freshness

Every response containing financial data should include:

{
  "source": "AMFI",
  "data_as_of": "2026-09-01",
  "retrieved_at": "2026-09-02T20:00:00Z"
}

Claude should use data_as_of when describing how current the information is.

18. Security

For a read-only mutual-fund MCP:

Do not accept arbitrary URLs from users.

Use an allowlist of provider domains.

Validate scheme codes.

Validate date values.

Limit historical query ranges.

Limit response size.

Do not execute provider-returned content.

Never expose API credentials.

Keep provider credentials in environment variables if a provider eventually requires authentication.

Example:

MF_PROVIDER_API_KEY=...

19. Financial-Safety Boundary

This MCP is a research/data tool.

It should not represent itself as:

A registered investment adviser

A guaranteed-return service

A trading/execution platform

The MCP can provide factual analysis such as:

5-year CAGR
volatility
drawdown
NAV history
fund comparison

Claude can explain the results, but users should understand that historical performance does not guarantee future performance.

20. Phase 1 Scope

Implement only:

search_funds
get_latest_nav
get_nav_history
calculate_fund_metrics
compare_funds

Data:

AMFI / selected API provider

Infrastructure:

Python
FastMCP
HTTP client
No database
No RAG
No embeddings

21. Future Tools

Only add these after Phase 1 works reliably:

get_scheme_details
get_aum
get_expense_ratio
get_riskometer
get_portfolio_holdings
get_sector_allocation
compare_portfolio_overlap
calculate_rolling_returns
calculate_sharpe_ratio
calculate_sortino_ratio

Each field must come from a verifiable source rather than an LLM estimate.

22. Design Principle

Keep the architecture simple:

Claude
   |
   | asks for data
   v
MCP
   |
   | fetches + calculates
   v
External mutual fund source

Not:

Claude
   |
RAG
   |
Vector DB
   |
Stale financial document

For numeric financial data, live structured retrieval should be preferred over semantic retrieval.

Definition of Done

The Phase 1 MCP is complete when Claude can successfully answer:

What is the latest NAV of <fund>?

Show the NAV history of <fund> for the last year.

What was the CAGR of <fund> over the last five years?

Compare <fund A> and <fund B> over the same period.

Which of these funds had the lower maximum drawdown?

and every numeric value in the answer can be traced back either to fetched NAV data or to a deterministic calculation performed by the MCP.