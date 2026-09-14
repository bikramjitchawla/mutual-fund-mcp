import math
from datetime import date

import pytest

from models.schemas import NavPoint
from services.advanced_analytics import advanced_metrics, rolling_returns
from services.errors import FundError
from services.mutual_funds import MutualFundService
from tests.test_mutual_funds import FakeProvider


def points(*observations):
    return [NavPoint(date.fromisoformat(day), nav) for day, nav in observations]


def test_rolling_aligns_forward_and_annualizes_actual_days():
    data = points(("2020-02-29", 100), ("2021-03-01", 110), ("2023-02-28", 133.1))
    result = rolling_returns(list(reversed(data)))
    first = result["1y"]["windows"][0]
    assert first["to"] == "2021-03-01"
    assert first["return_pct"] == round((1.1 ** (365.2425 / 366) - 1) * 100, 4)
    assert result["3y"]["count"] == 1
    assert result["3y"]["average_pct"] == pytest.approx(10.007, abs=0.001)


def test_short_history_has_null_rolling_summaries():
    result = rolling_returns(points(("2024-01-01", 100), ("2024-01-03", 110)))
    assert result["1y"] == {"count": 0, "average_pct": None, "best_pct": None, "worst_pct": None, "windows": []}


def test_recovery_and_longest_underwater_episode_are_distinct():
    data = points(("2020-01-01", 100), ("2020-01-11", 60), ("2020-01-21", 100), ("2020-02-01", 90), ("2020-03-01", 95))
    result = advanced_metrics(data)
    assert result["max_drawdown_pct"] == -40
    assert result["recovery_days"] == 10
    assert result["max_drawdown_duration_days"] == 40
    downside = math.sqrt((0.4 ** 2 + 0.1 ** 2) / 4 * 252)
    assert result["downside_volatility_pct"] == round(downside * 100, 4)
    assert result["sortino_ratio"] == pytest.approx(result["cagr_pct"] / 100 / downside, abs=0.0001)
    assert result["calmar_ratio"] == pytest.approx(result["cagr_pct"] / 40, abs=0.0001)


def test_deeper_unrecovered_drawdown_resets_recovery():
    result = advanced_metrics(points(("2020-01-01", 100), ("2020-01-02", 90), ("2020-01-03", 100), ("2020-01-04", 80)))
    assert result["recovery_days"] is None
    assert result["max_drawdown_pct"] == -20


def test_monotonic_series_has_undefined_ratios():
    result = advanced_metrics(points(("2020-01-01", 100), ("2021-01-01", 110)))
    assert result["calmar_ratio"] is None
    assert result["sortino_ratio"] is None
    assert result["recovery_days"] is None
    assert result["max_drawdown_duration_days"] == 0


@pytest.mark.parametrize("data", [[], points(("2024-01-01", 0)), points(("2024-01-01", math.nan)), points(("2024-01-01", 100), ("2024-01-01", 110))])
def test_invalid_nav_data(data):
    with pytest.raises(FundError):
        rolling_returns(data)


def test_service_comparisons_preserve_existing_fields_and_metadata():
    service = MutualFundService(FakeProvider())
    comparison = service.compare_funds(["1", "2"], "2024-01-01", "2024-12-31")
    fund = comparison["funds"][0]
    assert fund["volatility_pct"] == fund["annualized_volatility_pct"]
    assert "rolling_returns" in fund
    assert "sortino_ratio" in fund


def test_rolling_summary_includes_multiple_windows():
    result = rolling_returns(points(("2021-01-01", 100), ("2022-01-01", 110), ("2023-01-01", 99)))
    summary = result["1y"]
    expected = [(ratio ** (365.2425 / 365) - 1) * 100 for ratio in (1.1, 0.9)]
    assert summary["count"] == 2
    assert summary["average_pct"] == round(sum(expected) / 2, 4)
    assert summary["best_pct"] == round(max(expected), 4)
    assert summary["worst_pct"] == round(min(expected), 4)


def test_repeated_peaks_start_duration_at_latest_peak():
    result = advanced_metrics(points(("2024-01-01", 100), ("2024-01-03", 100), ("2024-01-04", 90), ("2024-01-05", 100)))
    assert result["max_drawdown_duration_days"] == 2
    assert result["recovery_days"] == 1


def test_one_observation_cannot_produce_comparison_metrics():
    with pytest.raises(FundError) as error:
        advanced_metrics(points(("2024-01-01", 100)))
    assert error.value.code == "NO_NAV_DATA"


def test_comparison_through_mcp_is_json_serializable(monkeypatch):
    import asyncio
    import importlib
    import json

    from fastmcp import Client

    server = importlib.import_module("mutual_fund_mcp.server")
    monkeypatch.setattr(server, "service", MutualFundService(FakeProvider()))

    async def call():
        async with Client(server.mcp) as client:
            return await client.call_tool("compare_funds", {
                "scheme_codes": ["1", "2"],
                "from_date": "2024-01-01",
                "to_date": "2024-12-31",
            })

    result = asyncio.run(call())
    assert not result.is_error
    payload = json.loads(result.content[0].text)
    json.dumps(payload, allow_nan=False)
    assert payload["funds"][0]["sortino_ratio"] is None
    assert payload["funds"][0]["rolling_returns"]["1y"]["count"] == 0
    assert "advanced_metrics_method" in payload
