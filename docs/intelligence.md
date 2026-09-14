# Benchmark and holdings intelligence

The new tools are available alongside the existing NAV and SIP tools. NAV and
benchmark calculations remain stateless. Holdings queries download public monthly
files on demand and persist validated snapshots in SQLite, which requires no
separate database server for Claude Desktop. PostgreSQL deployment and all-AMC
coverage are not included in this implementation.

## Benchmark comparison

Call `search_benchmarks()` first. The initial total-return catalog is:

- `NIFTY_50_TRI`
- `NIFTY_500_TRI`
- `NIFTY_NEXT_50_TRI`
- `NIFTY_MIDCAP_150_TRI`
- `NIFTY_SMALLCAP_250_TRI`

```json
{
  "scheme_code": "122639",
  "benchmark_code": "NIFTY_500_TRI",
  "from_date": "2021-01-01",
  "to_date": "2026-01-01"
}
```

Pass these arguments to `compare_fund_with_benchmark`. It returns each series'
CAGR, absolute return, volatility, maximum drawdown, sources, common observation
period, excluded-observation counts, CAGR difference in percentage points, and
Pearson correlation of successive returns. All calculations use the intersection
of observation dates, without interpolation or forward filling. Correlation is
null with fewer than two returns or a constant series. Volatility retains the
existing sample-standard-deviation and sqrt(252) convention; sparse observations
can distort this estimate. Choosing an index does not assert that it is the
fund's official benchmark.

The live adapter targets the public total-return data used by
[NSE Indices historical reports](https://www.niftyindices.com/reports/historical-data).
It makes bounded requests in windows of up to 365 days, checks numeric values,
and reports provider/schema failures explicitly. The endpoint is not a guaranteed
service. Live NSE requests timed out during implementation verification; mocked
adapter tests and end-to-end comparison using CSV inputs passed. No price-index
or index-fund proxy is silently substituted for TRI data.

### CSV provider for offline or unavailable live data

Set `MF_BENCHMARK_CSV_DIR` to an operator-managed directory. This explicitly selects
the CSV provider instead of live NSE. Create files named after supported codes,
for example `NIFTY_500_TRI.csv`, with the following structure:

```csv
date,value
2024-01-02,10000
2024-01-03,10020
```

**These two rows are synthetic format examples, not market data.** Supply actual
TRI observations from your authorized source. `date` uses YYYY-MM-DD; `value` is
the positive total-return index level. Missing files, malformed rows, duplicate
dates and non-finite values fail validation. Search lists only available files;
responses identify the source as operator-imported CSV. No arbitrary file path
can be requested through MCP.

For a local command:

```bash
MF_BENCHMARK_CSV_DIR=/absolute/path/to/indices uv run mutual-fund-mcp
```

For Claude Desktop, put this variable in the server's `env` configuration and
fully restart Claude. File changes are read on the next request.

## Public holdings coverage

The adapter discovers monthly XLSX links from the
[official PPFAS disclosure archive](https://amc.ppfas.com/downloads/portfolio-disclosure/index.php).
Initial supported schemes, represented once by their verified Direct Growth codes:

| Scheme code | Scheme |
|---|---|
| `122639` | Parag Parikh Flexi Cap Fund |
| `143269` | Parag Parikh Liquid Fund |
| `147481` | Parag Parikh ELSS Tax Saver Fund |
| `148958` | Parag Parikh Conservative Hybrid Fund |

A portfolio belongs to the scheme, not to an individual plan. Regular/IDCW plans
are not counted again. Other PPFAS schemes and other AMCs, including HDFC Mutual
Fund, are outside the current adapter's coverage. Older `.xls`-only months are
not supported; call `get_holdings_coverage` to see available XLSX months.

The importer checks sheet identity, portfolio date, expected columns, ISIN
checksums and numeric values. Market values are converted from lakhs to INR;
Excel percentage fractions are converted to percentage points. Duplicate ISIN
rows within a scheme are aggregated. Published rounded-zero weights remain zero,
while positive quantities still count as a holding.

**Scope:** ISIN-bearing cash securities, including stocks, bonds, fund units,
REITs and foreign securities. Cash/TREPS without ISIN, receivables/payables and
derivatives are excluded. Arbitrage cash legs are included, so a reported stock
weight is not necessarily net directional exposure. `sector` preserves the AMC's
industry/rating column; debt entries may contain a credit rating rather than an
industry. Weights are not rescaled to total 100%.

### Tools

- `get_holdings_coverage()` lists supported funds and discovered months.
- `get_fund_holdings(scheme_code, month=None)` returns a fund's holdings. Omitting
  `month` selects its latest available disclosure; explicit months use YYYY-MM.
- `get_funds_holding_stock(isin, month=None)` searches the supported funds at one
  common month, ranks by weight, and reports covered and unavailable funds.
  Omitting `month` selects the latest discovered month across supported funds.
- `get_stock_ownership_changes(isin, from_month, to_month)` compares quantities
  only for funds with both snapshots. It reports new positions, increases,
  reductions and exits, plus each fund's before/after quantity and weight.
- `get_funds_accumulating_stock(isin, month)`, `get_new_fund_buyers(isin, month)`,
  and `get_fund_exits_from_stock(isin, month)` filter the comparison with the
  immediately preceding calendar month.

Stock lookup uses exact ISIN matching, for example `INE040A01034` for HDFC Bank.
Empty results apply only to the successfully loaded covered funds, never the
whole mutual-fund market. Snapshot failures are exposed in `coverage` and are
never treated as exits. If no snapshots are available, the tool returns a
structured error instead of an empty market-wide result.

Quantity changes are **not verified buying or selling flows**: splits, mergers,
other corporate actions and arbitrage positions can change them. Missing or new
scheme coverage is excluded from change counts. Every result carries its dates
and scope; holdings results retain source URLs and retrieval times.

### Fund overlap

`compare_fund_overlap(scheme_codes, month=None, max_common_items=10,
max_unique_items=4, include_details=False)` compares 2–10 distinct scheme codes,
subject to the four-scheme coverage above. Repeated codes are deduplicated;
unsupported codes fail before retrieval. When no month is supplied, the tool
selects the latest disclosure month **common to every selected fund**. With an
explicit YYYY-MM month, all selected snapshots must be available. A missing or
invalid snapshot fails the comparison; no fund is silently dropped.

```json
{
  "scheme_codes": ["122639", "147481"],
  "month": "2026-08"
}
```

The default response is concise. `compact_summary.summary_text` is ready for a
client to display and contains the fund names, overlap percentage and level,
common-security count, top common holdings, top unique holdings, and a short
interpretation. `max_common_items` and `max_unique_items` control their respective
lists and accept values from 1 to 25. The structured
`compact_summary.comparisons` contains the same information for clients that
want to format it themselves.

Overlap levels use fixed thresholds:

- **High / 🔴:** 50% or more
- **Moderate / 🟡:** 25% to less than 50%
- **Low / 🟢:** less than 25%

Set `include_details` to `true` to add a complete `details` object containing:

- `shared_securities`: securities held by at least two selected funds, matched
  by ISIN, with each owner's name and reported portfolio weight.
- `funds[].unique_securities`: holdings found only in that fund among the selected
  funds. This does not imply uniqueness across the market.
- `pairwise`: each pair's shared securities, their overlap contributions, and
  `weighted_overlap_pct`. Each contribution is the smaller of the two reported
  weights; the total is their sum. Weights of 8% and 5% contribute 5 percentage
  points. Zero overlap means no shared weighted exposure in the imported scope.
- `common_to_all_isins` and `common_to_all_weighted_overlap_pct`: the intersection
  across every selected fund and the sum of the minimum weight across all funds
  for each common security. This is distinct from average pairwise overlap.

Compact common holdings are ordered by overlap contribution, and compact unique
holdings by their fund weight. Full shared securities are ordered by fund count,
then name and ISIN. Positive-quantity holdings with published rounded-zero weights
still count as shared, contributing zero weight. Weights are not renormalized:
identical imported portfolios can have less than 100% overlap because omitted
cash/derivatives are not part of this comparison.

**This compares all imported ISIN securities, not only stocks.** Bonds, REITs and
fund units can also overlap. It inherits the cash-security and arbitrage limitations
above and is not a measure of net directional exposure. Responses include each
fund's source, snapshot date, retrieval time and coverage.

Claude Desktop prompt:

> Which stocks and other securities overlap between Parag Parikh Flexi Cap
> Direct Growth and Parag Parikh ELSS Tax Saver Direct Growth for August 2026?
> Show each fund's weight, weighted overlap, and holdings unique to each fund.

### Persistence and refresh

Default database: `~/.local/share/mutual-fund-mcp/holdings.sqlite3`.
Override with `MF_HOLDINGS_DB=/absolute/path/holdings.sqlite3`.
The database is created lazily when a holdings request needs it. NAV/SIP calls do
not create it. Snapshots are transactionally stored by scheme and portfolio date,
with an index on ISIN and date. No raw workbooks or database files are committed.
The archive link list has a one-hour in-process cache. Explicit-month queries can
reuse persisted snapshots offline; latest-month discovery requires network access.

Queries ingest uncached months automatically. To pre-load a month or refresh
corrected disclosures, use the operator CLI:

```bash
uv run python -m mutual_fund_mcp.ingest --month 2026-08
uv run python -m mutual_fund_mcp.ingest --month 2026-08 --scheme-code 122639
```

The CLI prints per-fund outcomes and exits nonzero on any failure. Each successful
snapshot replacement is atomic; failed imports retain the previous valid snapshot.
There is no scheduled job. Docker Compose persists holdings in a named volume.

## Claude Desktop examples

After `uv sync --extra dev`, fully quit and reopen Claude Desktop. If your existing
launcher environment lacks the new dependency or tools, rerun `make install-claude`
from this checkout and restart Claude.

- “List the available benchmarks, then compare Parag Parikh Flexi Cap Direct
  Growth against Nifty 500 TRI from 2021-01-01 to 2026-01-01.”
- “Show your holdings coverage, then find the covered funds holding HDFC Bank
  (ISIN INE040A01034) for August 2026. Include the coverage limitations.”
- “Show Parag Parikh Flexi Cap's holdings for August 2026.”
- “Compare HDFC Bank ownership in the covered funds between July and August 2026.
  Separate quantity changes from conclusions about actual buying.”

## Verification

Unit/integration tests do not use external providers. Tests cover calendar
alignment, malformed data, missing history, CSV validation, workbook normalization,
atomic persistence, coverage gaps, ownership changes and MCP serialization.
Live public-provider checks are manual and should not block ordinary CI.
