import json
from datetime import date

import pytest

from clients.benchmarks import (
    Benchmark,
    BenchmarkProvider,
    CSVBenchmarkProvider,
    NSEBenchmarkProvider,
)
from models.schemas import NavPoint
from services.benchmarks import BenchmarkService
from services.errors import FundError
from tests.test_mutual_funds import FakeProvider


def response(rows):
    return json.dumps({"d": json.dumps(rows)}).encode()


def test_nse_chunking_filters_and_sorts_observations():
    calls = []

    def fetch(url, *, payload):
        calls.append(payload)
        return response(
            [
                {"Date": "02 Jan 2025", "TotalReturnsIndex": "1,100.00"},
                {"Date": "01 Jan 2024", "TotalReturnsIndex": "1000"},
                {"Date": "01 Jan 2024", "TotalReturnsIndex": "1000"},
            ]
        )

    benchmark, points = NSEBenchmarkProvider(fetch).get_history(
        "NIFTY_500_TRI", date(2024, 1, 1), date(2025, 1, 2)
    )
    assert len(calls) == 2
    assert [p.nav for p in points] == [1000, 1100]
    assert benchmark.return_type == "total_return"
    assert json.loads(calls[0]["cinfo"])["name"] == "NIFTY 500"


@pytest.mark.parametrize(
    "payload",
    [
        b"html",
        b"{}",
        b'{"d":{}}',
        response([{"Date": "bad", "TotalReturnsIndex": 100}]),
        response([{"Date": "01 Jan 2024", "TotalReturnsIndex": "NaN"}]),
        response([{"Date": "01 Jan 2024", "TotalReturnsIndex": -1}]),
    ],
)
def test_invalid_nse_responses(payload):
    with pytest.raises(FundError) as error:
        NSEBenchmarkProvider(lambda *a, **kw: payload).get_history(
            "NIFTY_50_TRI", date(2024, 1, 1), date(2024, 1, 2)
        )
    assert error.value.code == "INVALID_PROVIDER_RESPONSE"


def test_empty_nse_data_is_not_fabricated():
    with pytest.raises(FundError) as error:
        NSEBenchmarkProvider(lambda *a, **kw: response([])).get_history(
            "NIFTY_50_TRI", date(2024, 1, 1), date(2024, 1, 2)
        )
    assert error.value.code == "NO_BENCHMARK_DATA"


def test_unknown_benchmark_is_rejected_without_fetch():
    with pytest.raises(FundError) as error:
        NSEBenchmarkProvider(lambda *a, **kw: pytest.fail()).get_history(
            "../../secret", date(2024, 1, 1), date(2024, 1, 2)
        )
    assert error.value.code == "BENCHMARK_NOT_FOUND"


def test_csv_provider_validates_and_filters(tmp_path):
    path = tmp_path / "NIFTY_50_TRI.csv"
    path.write_text("date,value\n2023-01-01,100\n2024-01-01,110\n2025-01-01,121\n")
    provider = CSVBenchmarkProvider(str(tmp_path))
    assert len(provider.search_benchmarks("nifty 50")) == 1
    benchmark, points = provider.get_history(
        "NIFTY_50_TRI", date(2024, 1, 1), date(2025, 1, 1)
    )
    assert len(points) == 2
    assert benchmark.source == "Operator-imported TRI CSV"
    path.write_text("date,value\n2024-01-01,100\n2024-01-01,110\n")
    with pytest.raises(FundError):
        provider.get_history("NIFTY_50_TRI", date(2024, 1, 1), date(2025, 1, 1))


class IndexProvider(BenchmarkProvider):
    def __init__(self, points):
        self.points = points

    def search_benchmarks(self, query):
        return [Benchmark("TEST", "Test TRI")]

    def get_history(self, *args):
        return Benchmark("TEST", "Test TRI"), self.points


def test_comparison_uses_common_calendar_and_return_correlation():
    funds = FakeProvider()
    funds.points = [
        NavPoint(date(2024, 1, 1), 100),
        NavPoint(date(2024, 1, 2), 500),
        NavPoint(date(2024, 7, 1), 90),
        NavPoint(date(2025, 1, 1), 120),
    ]
    index = IndexProvider(
        [
            NavPoint(date(2024, 1, 1), 200),
            NavPoint(date(2024, 7, 1), 180),
            NavPoint(date(2025, 1, 1), 240),
        ]
    )
    result = BenchmarkService(funds, index).compare_fund_with_benchmark(
        "1", "TEST", "2024-01-01", "2025-01-01"
    )
    assert result["common_observations"] == 3
    assert result["excluded_observations"]["fund"] == 1
    assert result["fund"]["max_drawdown_pct"] == -10
    assert result["comparison"] == {"excess_return_pct": 0, "correlation": 1}
    assert result["fund"]["absolute_return_pct"] == 20


def test_constant_returns_have_null_correlation():
    funds = FakeProvider()
    funds.points = [NavPoint(date(2024, m, 1), 100) for m in (1, 2, 3)]
    result = BenchmarkService(
        funds, IndexProvider(funds.points)
    ).compare_fund_with_benchmark("1", "TEST", "2024-01-01", "2024-03-01")
    assert result["comparison"]["correlation"] is None


def test_insufficient_overlap_has_structured_error():
    with pytest.raises(FundError) as error:
        BenchmarkService(
            FakeProvider(), IndexProvider([NavPoint(date(2020, 1, 1), 100)])
        ).compare_fund_with_benchmark("1", "TEST", "2024-01-01", "2024-12-31")
    assert error.value.code == "INSUFFICIENT_OVERLAP"
