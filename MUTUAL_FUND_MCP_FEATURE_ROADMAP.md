# Mutual Fund MCP — Feature Roadmap

This document defines the next planned capabilities for `mutual-fund-mcp`.

The current project already provides:

- Mutual-fund search
- Latest NAV
- Historical NAV
- Absolute return
- CAGR
- Annualized volatility
- Maximum drawdown
- Side-by-side fund comparison

The next phase should improve the existing NAV analytics first, then expand into mutual-fund portfolio holdings and stock ownership intelligence.

---

# Goals

The project should evolve from:

> A stateless MCP server for Indian mutual-fund NAV data and deterministic analytics.

towards:

> An open-source mutual-fund intelligence MCP/API for performance, SIP analysis, benchmark comparison, and portfolio ownership research.

The project should continue to favor deterministic calculations over LLM-generated financial calculations.

The LLM or MCP client should interpret and explain results, while the server performs the actual calculations.

---

# Feature 1 — Advanced Fund Comparison

## Objective

Improve the existing `compare_funds` tool so that comparison is not limited to:

- Absolute return
- CAGR
- Annualized volatility
- Maximum drawdown

The comparison should help users understand:

- Return
- Risk
- Consistency
- Drawdown behavior
- Recovery behavior

---

## Proposed Metrics

### Existing metrics

- Absolute return
- CAGR
- Annualized volatility
- Maximum drawdown

### New metrics

- Rolling 1-year return
- Rolling 3-year return
- Average rolling return
- Best rolling return
- Worst rolling return
- Downside volatility
- Drawdown duration
- Recovery time
- Calmar ratio
- Sortino ratio

Sharpe ratio should only be added once the project has a clearly defined risk-free-rate source and methodology.

---

## Proposed Tool

The existing tool can be extended:

```python
compare_funds(
    scheme_codes: list[str],
    from_date: str,
    to_date: str
)
```

Optionally, rolling-period parameters can be introduced later:

```python
compare_funds(
    scheme_codes: list[str],
    from_date: str,
    to_date: str,
    rolling_periods: list[str] = ["1Y", "3Y"]
)
```

---

## Example Response

```json
{
  "period": {
    "from": "2021-01-01",
    "to": "2026-01-01"
  },
  "funds": [
    {
      "scheme_code": "123456",
      "scheme_name": "Example Flexi Cap Fund - Direct Growth",
      "absolute_return_pct": 121.4,
      "cagr_pct": 17.24,
      "annualized_volatility_pct": 13.7,
      "max_drawdown_pct": -18.9,
      "downside_volatility_pct": 9.2,
      "calmar_ratio": 0.91,
      "sortino_ratio": 1.54,
      "rolling_returns": {
        "1y": {
          "average_pct": 15.3,
          "best_pct": 41.7,
          "worst_pct": -11.8
        },
        "3y": {
          "average_pct": 16.4,
          "best_pct": 23.6,
          "worst_pct": 8.3
        }
      },
      "max_drawdown_duration_days": 284,
      "recovery_days": 192
    }
  ]
}
```

---

## Important Design Rule

All calculations should remain deterministic and implemented in Python.

The LLM should not calculate:

- CAGR
- Rolling returns
- XIRR
- Drawdown
- Volatility
- Ratios

The MCP should return structured results.

---

# Feature 2 — SIP and XIRR Analysis

## Objective

Add SIP analysis because many Indian retail investors invest monthly rather than through lump-sum investments.

CAGR alone does not accurately describe an investor's experience when money is invested over time.

---

## Proposed Tool

```python
calculate_sip_returns(
    scheme_code: str,
    monthly_amount: float,
    from_date: str,
    to_date: str
)
```

---

## Expected Behavior

For each monthly SIP installment:

1. Determine the SIP investment date.
2. Find the first available NAV observation on or after that date.
3. Calculate units purchased.

Formula:

```text
units_purchased = monthly_amount / NAV
```

Total units:

```text
total_units = sum(all SIP units)
```

Portfolio value:

```text
current_value = total_units × ending NAV
```

The cash-flow series should then be used to calculate XIRR.

---

## Example

Input:

```json
{
  "scheme_code": "123456",
  "monthly_amount": 10000,
  "from_date": "2021-01-01",
  "to_date": "2026-01-01"
}
```

Output:

```json
{
  "scheme_code": "123456",
  "monthly_amount": 10000,
  "installments": 60,
  "total_invested": 600000,
  "total_units": 4321.8421,
  "ending_nav": 191.41,
  "current_value": 827412,
  "profit": 227412,
  "absolute_gain_pct": 37.90,
  "xirr_pct": 12.91,
  "data_as_of": "2026-01-01"
}
```

---

## Future Extension

Add:

```python
compare_sip_returns(
    scheme_codes: list[str],
    monthly_amount: float,
    from_date: str,
    to_date: str
)
```

Example result:

```text
₹10,000 monthly SIP for 5 years

Fund                     Invested     Value       XIRR
------------------------------------------------------
Fund A                    ₹600k       ₹827k      12.9%
Fund B                    ₹600k       ₹851k      13.8%
Fund C                    ₹600k       ₹792k      11.6%
```

---

## Optional Future Enhancements

- Step-up SIP
- Quarterly SIP
- Weekly SIP
- SIP date selection
- Missed-installment handling
- Lump-sum + SIP combination
- SIP rolling-return analysis

These should not be included in the first implementation.

---

# Feature 3 — Benchmark Comparison

## Objective

Allow a mutual fund to be compared directly against its benchmark or another market index.

The key question should become:

> Did the fund generate enough excess return to justify its active risk?

---

## Proposed Tool

```python
compare_fund_with_benchmark(
    scheme_code: str,
    benchmark_code: str,
    from_date: str,
    to_date: str
)
```

---

## Initial Metrics

- Fund CAGR
- Benchmark CAGR
- Excess return
- Fund volatility
- Benchmark volatility
- Fund maximum drawdown
- Benchmark maximum drawdown
- Correlation

---

## Example Response

```json
{
  "fund": {
    "name": "Example Flexi Cap Fund",
    "cagr_pct": 18.7,
    "volatility_pct": 13.4,
    "max_drawdown_pct": -17.6
  },
  "benchmark": {
    "name": "Nifty 500 TRI",
    "cagr_pct": 15.8,
    "volatility_pct": 15.1,
    "max_drawdown_pct": -23.2
  },
  "comparison": {
    "excess_return_pct": 2.9,
    "correlation": 0.84
  }
}
```

---

## Future Metrics

Once a reliable benchmark and risk-free-rate data source exists, add:

- Alpha
- Beta
- Tracking error
- Information ratio
- Sharpe ratio
- Upside capture
- Downside capture

---

## Benchmark Data Considerations

Benchmark support introduces a new data-source requirement.

Possible approaches:

1. Integrate an official/public index provider.
2. Maintain a dedicated benchmark-provider abstraction.
3. Keep benchmark retrieval separate from mutual-fund providers.

Suggested interface:

```python
class BenchmarkProvider(ABC):

    def search_benchmarks(self, query: str):
        ...

    def get_history(
        self,
        benchmark_code: str,
        from_date: date,
        to_date: date
    ):
        ...
```

This keeps index data separate from AMFI/MFAPI fund data.

---

# Feature 4 — Stock → Mutual Funds Lookup

This feature was originally discussed as the sixth feature in the broader roadmap.

## Objective

Support the inverse relationship:

Current direction:

```text
Fund → Stocks
```

New direction:

```text
Stock → Mutual Funds
```

This allows users to ask:

> Which mutual funds hold HDFC Bank?

or:

> Which funds have the highest exposure to Reliance Industries?

---

## Proposed Tool

```python
get_funds_holding_stock(
    isin: str
)
```

ISIN should be preferred over company-name matching.

---

## Example Response

```json
{
  "security": {
    "isin": "INE040A01034",
    "name": "HDFC Bank Ltd"
  },
  "data_as_of": "2026-08-31",
  "funds": [
    {
      "scheme_code": "100001",
      "scheme_name": "Example Large Cap Fund",
      "portfolio_weight_pct": 8.2
    },
    {
      "scheme_code": "100002",
      "scheme_name": "Example Flexi Cap Fund",
      "portfolio_weight_pct": 7.6
    }
  ]
}
```

---

# Holdings Data Layer

Stock ownership intelligence requires fund portfolio holdings.

Suggested normalized holding structure:

```text
scheme_code
portfolio_date
isin
security_name
sector
quantity
market_value
portfolio_weight
```

ISIN should be the canonical security identifier.

Avoid relying on company-name matching because the same security may appear as:

```text
HDFC BANK LTD
HDFC Bank Limited
HDFC BANK
HDFC Bank Ltd.
```

---

# Future Stock Ownership Intelligence

Once monthly portfolio snapshots are stored, the MCP can support much stronger queries.

---

## Tool — Stock Ownership Changes

```python
get_stock_ownership_changes(
    isin: str,
    from_month: str,
    to_month: str
)
```

Example:

```json
{
  "security": "HDFC Bank Ltd",
  "new_fund_buyers": 5,
  "funds_increasing_position": 38,
  "funds_reducing_position": 12,
  "funds_exiting_position": 2
}
```

---

## Tool — Funds Accumulating a Stock

```python
get_funds_accumulating_stock(
    isin: str,
    month: str
)
```

---

## Tool — New Fund Buyers

```python
get_new_fund_buyers(
    isin: str,
    month: str
)
```

---

## Tool — Fund Exits

```python
get_fund_exits_from_stock(
    isin: str,
    month: str
)
```

---

# Architecture

## Current Architecture

The current stateless model is appropriate for NAV analytics:

```text
User / MCP Client
        |
        v
Mutual Fund MCP
        |
        v
Provider Abstraction
     /       \
    v         v
 MFAPI      AMFI
```

This architecture should remain for:

- NAV retrieval
- Historical NAV
- Fund metrics
- Advanced comparison
- SIP analysis
- Benchmark comparison

---

# Holdings Architecture

Historical holdings should use persistence.

Recommended architecture:

```text
AMC / AMFI Portfolio Files
            |
            v
      Holdings Ingestion
            |
            v
        Normalization
            |
            v
        PostgreSQL
            |
            v
     Analytics Service
            |
            v
      Mutual Fund MCP
            |
            v
 Claude / ChatGPT / Agents
```

---

# Suggested PostgreSQL Tables

## funds

```text
scheme_code
scheme_name
fund_house
category
```

## securities

```text
isin
security_name
sector
industry
market_cap_category
```

## portfolio_snapshots

```text
id
scheme_code
portfolio_date
source
retrieved_at
```

## portfolio_holdings

```text
snapshot_id
isin
quantity
market_value
portfolio_weight
```

---

# Version Roadmap

## v0.2 — Better NAV Intelligence

No database required.

Add:

```text
calculate_rolling_returns
calculate_sip_returns
compare_sip_returns
compare_fund_with_benchmark
```

Improve:

```text
compare_funds
```

Add metrics:

```text
rolling returns
downside volatility
drawdown duration
recovery time
Sortino ratio
Calmar ratio
```

---

## v0.3 — Holdings Intelligence

Introduce holdings ingestion.

Add:

```text
get_fund_holdings
get_funds_holding_stock
```

Potentially also:

```text
get_sector_allocation
get_market_cap_allocation
```

---

## v0.4 — Historical Ownership Intelligence

Introduce monthly portfolio snapshots.

Add:

```text
get_stock_ownership_changes
get_funds_accumulating_stock
get_new_fund_buyers
get_fund_exits_from_stock
```

---

# Engineering Improvements

These improvements can be developed alongside the new features.

---

## 1. Add Provider Caching

AMFI's latest NAV feed should not be downloaded repeatedly for identical requests.

A simple in-memory TTL cache is sufficient initially.

No Redis is required.

Example:

```text
NAVAll.txt cache TTL: 5–15 minutes
```

---

## 2. Improve Multi-Fund Comparison Performance

The current implementation fetches each fund sequentially.

Consider:

```python
get_nav_history_many(
    scheme_codes,
    from_date,
    to_date
)
```

For AMFI this can significantly reduce duplicate downloads.

---

## 3. Reuse HTTP Connections

Consider using:

```python
httpx.AsyncClient
```

or a reusable long-lived `httpx.Client`.

Benefits:

- Connection pooling
- Lower latency
- Concurrent fund comparison
- Better scaling for remote MCP deployments

---

## 4. Typed Response Models

Replace loosely structured dictionary outputs over time with explicit response models.

Examples:

```text
FundSearchResponse
LatestNAVResponse
FundMetricsResponse
FundComparisonResponse
SIPReturnResponse
BenchmarkComparisonResponse
FundHoldingResponse
StockOwnershipResponse
```

Pydantic models would work well.

---

## 5. CI Improvements

Keep CI lightweight.

Recommended additions:

```text
ruff
type checking
pytest coverage
package build
```

A separate scheduled provider smoke test can verify:

```text
MFAPI search still works
AMFI NAVAll parsing still works
Known scheme returns NAV
External response schema has not changed
```

External provider tests should not block every pull request because provider outages may cause false failures.

---

# Non-Goals

The following should not be introduced without a clear need:

## RAG / Vector Database

The project primarily works with structured financial data.

SQL and deterministic analytics are better suited than embeddings for:

- NAV data
- Holdings
- Portfolio weights
- Fund comparisons
- Stock ownership

RAG should only be considered later for unstructured content such as:

- Scheme documents
- AMC commentary
- Factsheets
- Fund-manager letters

---

## AI-Based Financial Calculations

Do not ask the LLM to compute investment metrics.

The backend should calculate them deterministically.

The LLM should only:

- Explain results
- Summarize comparisons
- Answer natural-language questions using MCP outputs

---

# Suggested Immediate Implementation Order

The next development sequence should be:

```text
1. calculate_rolling_returns
2. calculate_sip_returns
3. compare_sip_returns
4. benchmark provider abstraction
5. compare_fund_with_benchmark
6. holdings data-source research
7. get_fund_holdings
8. get_funds_holding_stock
```

This keeps the first milestone compatible with the existing stateless architecture and delays database complexity until holdings intelligence actually requires it.

---

# Long-Term Direction

The project can eventually evolve through the following stages:

```text
NAV MCP
   |
   v
Advanced Fund Analytics
   |
   v
SIP + Benchmark Intelligence
   |
   v
Portfolio Holdings
   |
   v
Stock Ownership Intelligence
   |
   v
Indian Mutual Fund Intelligence MCP
```

The goal should not simply be to return more financial data.

The goal should be to enable useful questions such as:

> Which fund has delivered the most consistent rolling returns?

> How would a ₹10,000 monthly SIP have performed across these funds?

> Did this active fund outperform its benchmark after taking additional risk?

> Which mutual funds currently hold HDFC Bank?

> Which funds increased exposure to HDFC Bank last month?

> Which stocks are being accumulated by the largest number of mutual funds?

Those questions provide a clear path from a NAV lookup tool to a useful mutual-fund research platform.
