"""Comparison on the intersection of fund and benchmark observation dates."""

import statistics
from dataclasses import asdict

from clients.benchmarks import BenchmarkProvider
from services.advanced_analytics import normalize_nav_points
from services.analytics import calculate_metrics
from services.errors import FundError
from services.mutual_funds import MutualFundService


class BenchmarkService:
    def __init__(self, fund_provider, benchmark_provider: BenchmarkProvider):
        self.funds = fund_provider
        self.benchmarks = benchmark_provider

    def search_benchmarks(self, query: str = "") -> dict:
        return {
            "results": [asdict(b) for b in self.benchmarks.search_benchmarks(query)],
            "retrieved_at": MutualFundService._now(),
        }

    def compare_fund_with_benchmark(
        self, scheme_code: str, benchmark_code: str, from_date: str, to_date: str
    ) -> dict:
        start, end = MutualFundService._date_range(from_date, to_date)
        benchmark, index_points = self.benchmarks.get_history(
            benchmark_code, start, end
        )
        scheme, fund_points = self.funds.get_nav_history(scheme_code, start, end)
        fund = {
            p.date: p
            for p in normalize_nav_points(fund_points)
            if start <= p.date <= end
        }
        index = {
            p.date: p
            for p in normalize_nav_points(index_points)
            if start <= p.date <= end
        }
        dates = sorted(fund.keys() & index.keys())
        if len(dates) < 2:
            raise FundError(
                "INSUFFICIENT_OVERLAP",
                "At least two common fund and benchmark dates are required.",
            )
        fund_series, index_series = [fund[d] for d in dates], [index[d] for d in dates]
        fm, bm = calculate_metrics(fund_series), calculate_metrics(index_series)
        fr = [b.nav / a.nav - 1 for a, b in zip(fund_series, fund_series[1:])]
        br = [b.nav / a.nav - 1 for a, b in zip(index_series, index_series[1:])]
        correlation = None
        if len(fr) >= 2:
            try:
                correlation = round(statistics.correlation(fr, br), 6)
            except statistics.StatisticsError:
                pass
        return {
            "period": {"from": from_date, "to": to_date},
            "observation_period": {
                "from": dates[0].isoformat(),
                "to": dates[-1].isoformat(),
            },
            "common_observations": len(dates),
            "excluded_observations": {
                "fund": len(fund) - len(dates),
                "benchmark": len(index) - len(dates),
            },
            "fund": {
                "scheme_code": scheme.scheme_code,
                "name": scheme.scheme_name,
                **fm,
                "volatility_pct": fm["annualized_volatility_pct"],
                "source": self.funds.source,
            },
            "benchmark": {
                **asdict(benchmark),
                **bm,
                "volatility_pct": bm["annualized_volatility_pct"],
            },
            "comparison": {
                "excess_return_pct": round(fm["cagr_pct"] - bm["cagr_pct"], 4),
                "correlation": correlation,
            },
            "method": "Both series use identical common dates; no forward filling. Excess return is CAGR difference in percentage points. Pearson correlation of successive common-date returns; null if insufficient or constant. Volatility uses sample stdev * sqrt(252), so sparse history can distort it.",
            "data_as_of": dates[-1].isoformat(),
            "retrieved_at": MutualFundService._now(),
        }
