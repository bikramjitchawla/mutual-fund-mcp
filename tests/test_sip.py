import asyncio
import importlib
import json
import math
from datetime import date

import pytest
from fastmcp import Client

from models.schemas import FundScheme, NavPoint
from services.errors import FundError
from services.mutual_funds import MutualFundService
from services.sip import _xirr_pct, calculate_sip
from tests.test_mutual_funds import FakeProvider


def points(*observations):
    return [NavPoint(date.fromisoformat(day), nav) for day, nav in observations]


def test_month_end_clamp_does_not_drift_and_end_is_exclusive():
    data = points(("2024-01-31", 100), ("2024-02-29", 100), ("2024-04-01", 100), ("2024-04-30", 100))
    result = calculate_sip(data, 1000, date(2024, 1, 31), date(2024, 4, 30))
    assert result["installments"] == 3
    assert [i["scheduled_date"] for i in result["installment_details"]] == ["2024-01-31", "2024-02-29", "2024-03-31"]
    assert result["installment_details"][-1]["investment_date"] == "2024-04-01"
    assert result["total_invested"] == result["current_value"] == 3000
    assert result["total_units"] == 30
    assert result["xirr_pct"] == 0
    assert result["xirr_status"] == "calculated"


def test_roadmap_five_year_schedule_has_sixty_installments():
    data = [NavPoint(date(year, month, 1), 100) for year in range(2021, 2026) for month in range(1, 13)]
    data.append(NavPoint(date(2026, 1, 1), 100))
    result = calculate_sip(data, 10000, date(2021, 1, 1), date(2026, 1, 1))
    assert result["installments"] == result["scheduled_installments"] == 60
    assert result["total_invested"] == 600000
    assert result["unfilled_installment_dates"] == []


def test_units_and_profit_use_unrounded_units():
    data = points(("2024-01-01", 3), ("2024-02-01", 7), ("2024-03-01", 13))
    result = calculate_sip(list(reversed(data)), 1000, date(2024, 1, 1), date(2024, 3, 1))
    units = 1000 / 3 + 1000 / 7
    assert result["total_units"] == round(units, 8)
    assert result["current_value"] == round(units * 13, 2)
    assert result["profit"] == round(units * 13 - 2000, 2)
    assert result["absolute_gain_pct"] == round((units * 13 / 2000 - 1) * 100, 4)


def test_unfillable_dates_are_exposed_and_valuation_uses_last_observation():
    data = points(("2024-01-02", 100), ("2024-02-02", 100), ("2024-05-01", 1000))
    result = calculate_sip(data, 1000, date(2024, 1, 1), date(2024, 4, 1))
    assert result["scheduled_installments"] == 3
    assert result["installments"] == 2
    assert result["unfilled_installment_dates"] == ["2024-03-01"]
    assert result["data_as_of"] == "2024-02-02"
    assert result["current_value"] == 2000


def test_delayed_installments_can_execute_on_same_nav_date():
    result = calculate_sip(points(("2024-03-04", 100)), 1000, date(2024, 1, 1), date(2024, 4, 1))
    assert result["installments"] == 3
    assert {item["investment_date"] for item in result["installment_details"]} == {"2024-03-04"}
    assert result["xirr_pct"] is None
    assert result["xirr_status"] == "undefined_or_out_of_bounds"


@pytest.mark.parametrize("rate", [-0.5, 0, 0.1, 2])
def test_xirr_known_one_year_cashflows(rate):
    assert _xirr_pct([(date(2023, 1, 1), 100)], date(2024, 1, 1), 100 * (1 + rate)) == pytest.approx(rate * 100)


def test_xirr_multiflow_residual():
    deposits = [(date(2023, 1, 1), 1000), (date(2023, 6, 1), 1000)]
    end = date(2024, 1, 1)
    rate = _xirr_pct(deposits, end, 2200) / 100
    assert abs(sum(amount * (1 + rate) ** ((end - day).days / 365) for day, amount in deposits) - 2200) < 0.001


def test_xirr_uses_act_365_in_leap_year():
    assert _xirr_pct([(date(2024, 1, 1), 100)], date(2025, 1, 1), 110) == round((1.1 ** (365 / 366) - 1) * 100, 4)


def test_same_day_terminal_contribution_does_not_change_return():
    assert _xirr_pct([(date(2023, 1, 1), 100), (date(2024, 1, 1), 50)], date(2024, 1, 1), 160) == 10


def test_extreme_xirr_returns_null_without_overflow():
    assert _xirr_pct([(date(2024, 1, 1), 1)], date(2024, 1, 2), 1e300) is None


@pytest.mark.parametrize("amount", [0, -1, math.nan, math.inf, True, "100"])
def test_invalid_amounts(amount):
    with pytest.raises(FundError) as error:
        calculate_sip([], amount, date(2024, 1, 1), date(2024, 2, 1))
    assert error.value.code == "INVALID_AMOUNT"


@pytest.mark.parametrize("data", [[], points(("2024-01-01", 0)), points(("2024-01-01", math.nan)), points(("2024-01-01", 100), ("2024-01-01", 110))])
def test_invalid_nav_data(data):
    with pytest.raises(FundError):
        calculate_sip(data, 1000, date(2024, 1, 1), date(2024, 2, 1))


def test_overflow_is_structured_calculation_error():
    with pytest.raises(FundError) as error:
        calculate_sip(points(("2024-01-01", 1e-300)), 1e300, date(2024, 1, 1), date(2024, 2, 1))
    assert error.value.code == "CALCULATION_ERROR"


def test_service_metadata_and_different_coverage():
    class DifferentHistoryProvider(FakeProvider):
        def get_nav_history(self, scheme_code, from_date, to_date):
            history = self.points if scheme_code == "1" else self.points[:1]
            return FundScheme(scheme_code, f"Fund {scheme_code}", "Test AMC"), history

    result = MutualFundService(DifferentHistoryProvider()).compare_sip_returns(["1", "2", "1"], 1000, "2024-01-01", "2024-12-31")
    assert [fund["scheme_code"] for fund in result["funds"]] == ["1", "2"]
    assert result["funds"][0]["installments"] == 12
    assert result["funds"][1]["installments"] == 1
    assert result["source"] == "Test Provider"
    assert result["data_as_of"] == "2024-01-02"
    assert result["funds"][0]["data_as_of"] == "2024-12-31"
    assert result["retrieved_at"].endswith("Z")
    assert "method" in result["funds"][0]


@pytest.mark.parametrize("codes", [[], ["1"], ["1", "1"], [str(i) for i in range(11)]])
def test_comparison_validates_distinct_codes(codes):
    with pytest.raises(FundError) as error:
        MutualFundService(FakeProvider()).compare_sip_returns(codes, 1000, "2024-01-01", "2024-12-31")
    assert error.value.code == "INVALID_COMPARISON"


@pytest.mark.parametrize("start,end", [("bad", "2024-01-01"), ("2024-01-02", "2024-01-01"), ("2024-01-01", "2024-01-01"), ("2010-01-01", "2024-01-01")])
def test_service_rejects_invalid_dates_before_fetch(start, end):
    class NoFetchProvider(FakeProvider):
        def get_nav_history(self, *args):
            pytest.fail("Invalid input must not reach the provider")

    with pytest.raises(FundError) as error:
        MutualFundService(NoFetchProvider()).calculate_sip_returns("1", 1000, start, end)
    assert error.value.code == "INVALID_DATE_RANGE"


def test_mcp_tools_return_serializable_results_and_structured_errors(monkeypatch):
    server = importlib.import_module("mutual_fund_mcp.server")
    monkeypatch.setattr(server, "service", MutualFundService(FakeProvider()))

    async def call():
        async with Client(server.mcp) as client:
            common = {"monthly_amount": 1000, "from_date": "2024-01-01", "to_date": "2024-12-31"}
            for tool, codes in [("calculate_sip_returns", {"scheme_code": "1"}), ("compare_sip_returns", {"scheme_codes": ["1", "2"]})]:
                result = await client.call_tool(tool, {**common, **codes})
                assert not result.is_error
                payload = json.loads(result.content[0].text)
                json.dumps(payload, allow_nan=False)
                assert "source" in payload
            result = await client.call_tool("calculate_sip_returns", {**common, "scheme_code": "1", "monthly_amount": -1})
            assert json.loads(result.content[0].text)["error"]["code"] == "INVALID_AMOUNT"

    asyncio.run(call())
