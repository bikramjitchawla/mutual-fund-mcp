import asyncio
import copy
import importlib
import json

import pytest
from fastmcp import Client

from services.errors import FundError
from services.overlap import calculate_overlap
from tests.test_holdings import ISIN, OTHER, service, snapshot

THIRD = "INE002A01018"
FOURTH = "INE154A01025"
CODES = ["122639", "147481", "148958"]


def portfolio(code, positions, month="2026-08"):
    result = snapshot(code, month)
    result["retrieved_at"] = "2026-09-01T00:00:00Z"
    result["holdings"] = [
        {
            "isin": isin,
            "security_name": f"Security {isin}",
            "sector": "Example",
            "quantity": quantity,
            "market_value": 100,
            "portfolio_weight_pct": weight,
        }
        for isin, weight, quantity in positions
    ]
    return result


def test_pairwise_overlap_matches_isin_not_names_and_does_not_renormalize():
    a = portfolio(CODES[0], [(ISIN, 8, 100), (OTHER, 4, 50)])
    b = portfolio(CODES[1], [(ISIN, 5, 50), (THIRD, 7, 10)])
    a["holdings"][0]["security_name"] = "HDFC BANK LTD"
    b["holdings"][0]["security_name"] = "HDFC Bank Limited"
    b["holdings"][1]["security_name"] = a["holdings"][1]["security_name"]
    result = calculate_overlap([a, b])
    assert result["shared_security_count"] == 1
    shared = result["shared_securities"][0]
    assert shared["isin"] == ISIN
    assert [f["portfolio_weight_pct"] for f in shared["funds"]] == [8, 5]
    assert result["pairwise"][0]["weighted_overlap_pct"] == 5
    assert (
        result["pairwise"][0]["shared_securities"][0]["overlap_contribution_pct"] == 5
    )
    assert result["common_to_all_weighted_overlap_pct"] == 5
    assert [f["unique_security_count"] for f in result["funds"]] == [1, 1]
    assert result["funds"][0]["reported_weight_sum_pct"] == 12


def test_three_funds_distinguishes_any_shared_common_to_all_and_unique():
    data = [
        portfolio(CODES[0], [(ISIN, 8, 1), (OTHER, 4, 1), (FOURTH, 3, 1)]),
        portfolio(CODES[1], [(ISIN, 5, 1), (THIRD, 7, 1)]),
        portfolio(CODES[2], [(ISIN, 6, 1), (OTHER, 2, 1), (THIRD, 1, 1)]),
    ]
    result = calculate_overlap(data)
    assert result["shared_security_count"] == 3
    assert result["common_to_all_security_count"] == 1
    assert result["common_to_all_isins"] == [ISIN]
    assert result["common_to_all_weighted_overlap_pct"] == 5
    assert [p["weighted_overlap_pct"] for p in result["pairwise"]] == [5, 8, 6]
    assert [p["shared_security_count"] for p in result["pairwise"]] == [1, 2, 2]
    assert [f["unique_security_count"] for f in result["funds"]] == [1, 0, 0]
    assert result["shared_securities"][0]["fund_count"] == 3


def test_disjoint_portfolios_have_zero_overlap():
    result = calculate_overlap(
        [portfolio(CODES[0], [(ISIN, 8, 1)]), portfolio(CODES[1], [(OTHER, 5, 1)])]
    )
    assert result["shared_securities"] == []
    assert result["common_to_all_isins"] == []
    assert result["pairwise"][0]["weighted_overlap_pct"] == 0


def test_positive_quantity_zero_weight_is_shared_but_zero_quantity_is_excluded():
    result = calculate_overlap(
        [
            portfolio(CODES[0], [(ISIN, 0, 1), (OTHER, 5, 0)]),
            portfolio(CODES[1], [(ISIN, 2, 1), (OTHER, 5, 1)]),
        ]
    )
    assert result["shared_security_count"] == 1
    assert result["pairwise"][0]["weighted_overlap_pct"] == 0
    assert result["funds"][1]["unique_securities"][0]["isin"] == OTHER


def test_empty_imported_portfolio_and_identical_partial_portfolios():
    result = calculate_overlap(
        [portfolio(CODES[0], []), portfolio(CODES[1], [(ISIN, 5, 1)])]
    )
    assert result["pairwise"][0]["weighted_overlap_pct"] == 0
    result = calculate_overlap(
        [portfolio(c, [(ISIN, 12.345678, 1)]) for c in CODES[:2]]
    )
    assert result["pairwise"][0]["weighted_overlap_pct"] == 12.345678


def test_calculation_is_symmetric_and_does_not_mutate_snapshots():
    data = [
        portfolio(c, [(ISIN, 8 - i, 1), (OTHER, 1.234567, 1)])
        for i, c in enumerate(CODES[:2])
    ]
    original = copy.deepcopy(data)
    forward = calculate_overlap(data)
    reverse = calculate_overlap(list(reversed(data)))
    assert (
        forward["pairwise"][0]["weighted_overlap_pct"]
        == reverse["pairwise"][0]["weighted_overlap_pct"]
    )
    assert original == data


def test_calculator_refuses_mixed_months():
    with pytest.raises(FundError):
        calculate_overlap(
            [portfolio(CODES[0], [], "2026-07"), portfolio(CODES[1], [], "2026-08")]
        )


def test_service_selects_latest_common_month_not_each_funds_latest(tmp_path):
    data = {
        (code, "2026-07"): portfolio(code, [(ISIN, 5, 1)], "2026-07")
        for code in CODES[:2]
    }
    data[(CODES[0], "2026-08")] = portfolio(CODES[0], [(ISIN, 10, 1)])
    svc = service(tmp_path, data)
    result = svc.compare_fund_overlap([*CODES[:2], CODES[0]])
    assert result["month"] == "2026-07"
    assert result["data_as_of"] == "2026-07-31"
    assert result["coverage"]["compared_scheme_codes"] == CODES[:2]
    assert result["coverage"]["complete_for_requested_funds"]
    assert svc.provider.downloads == 2
    assert all(f["source"] and f["retrieved_at"] for f in result["funds"])
    svc.provider.disclosures = lambda: pytest.fail(
        "Explicit cached month should work offline"
    )
    svc.compare_fund_overlap(CODES[:2], "2026-07")


def test_service_missing_snapshot_is_an_error_not_partial_overlap(tmp_path):
    svc = service(
        tmp_path, {(CODES[0], "2026-08"): portfolio(CODES[0], [(ISIN, 5, 1)])}
    )
    with pytest.raises(FundError) as error:
        svc.compare_fund_overlap(CODES[:2], "2026-08")
    assert error.value.code == "NO_HOLDINGS_DATA"


def test_service_no_common_month_is_structured_error(tmp_path):
    svc = service(
        tmp_path,
        {
            (CODES[0], "2026-07"): portfolio(CODES[0], [], "2026-07"),
            (CODES[1], "2026-08"): portfolio(CODES[1], []),
        },
    )
    with pytest.raises(FundError) as error:
        svc.compare_fund_overlap(CODES[:2])
    assert error.value.code == "NO_HOLDINGS_DATA"
    assert svc.provider.downloads == 0


@pytest.mark.parametrize(
    "codes,error_code",
    [
        ([], "INVALID_COMPARISON"),
        ([CODES[0]], "INVALID_COMPARISON"),
        ([CODES[0], CODES[0]], "INVALID_COMPARISON"),
        ([str(i) for i in range(11)], "INVALID_COMPARISON"),
        ([CODES[0], "118955"], "UNSUPPORTED_HOLDINGS_SCHEME"),
    ],
)
def test_invalid_selection_rejected_before_fetch(tmp_path, codes, error_code):
    svc = service(tmp_path, {})
    svc.provider.disclosures = lambda: pytest.fail("Invalid input must not fetch")
    with pytest.raises(FundError) as error:
        svc.compare_fund_overlap(codes)
    assert error.value.code == error_code


def test_invalid_month_rejected_before_fetch(tmp_path):
    svc = service(tmp_path, {})
    with pytest.raises(FundError) as error:
        svc.compare_fund_overlap(CODES[:2], "2026-13")
    assert error.value.code == "INVALID_MONTH"


def test_overlap_tool_through_mcp(tmp_path, monkeypatch):
    server = importlib.import_module("mutual_fund_mcp.server")
    svc = service(
        tmp_path,
        {
            (c, "2026-08"): portfolio(c, [(ISIN, 8 - i, 1)])
            for i, c in enumerate(CODES[:2])
        },
    )
    monkeypatch.setattr(server, "holdings_service", svc)

    async def call():
        async with Client(server.mcp) as client:
            result = await client.call_tool(
                "compare_fund_overlap", {"scheme_codes": CODES[:2], "month": "2026-08"}
            )
            assert not result.is_error
            payload = json.loads(result.content[0].text)
            json.dumps(payload, allow_nan=False)
            assert payload["pairwise"][0]["weighted_overlap_pct"] == 7
            result = await client.call_tool(
                "compare_fund_overlap", {"scheme_codes": [CODES[0], "118955"]}
            )
            assert (
                json.loads(result.content[0].text)["error"]["code"]
                == "UNSUPPORTED_HOLDINGS_SCHEME"
            )

    asyncio.run(call())
