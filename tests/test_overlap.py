import asyncio
import copy
import importlib
import json

import pytest
from fastmcp import Client

from services.errors import FundError
from services.overlap import calculate_overlap, compact_overlap
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


@pytest.mark.parametrize(
    "weight,level,indicator",
    [
        (75, "High", "🔴"),
        (50, "High", "🔴"),
        (49.99, "Moderate", "🟡"),
        (25, "Moderate", "🟡"),
        (24.99, "Low", "🟢"),
        (0, "Low", "🟢"),
    ],
)
def test_compact_summary_classifies_overlap(weight, level, indicator):
    details = calculate_overlap(
        [
            portfolio(CODES[0], [(ISIN, weight, 1)]),
            portfolio(CODES[1], [(ISIN, weight, 1)]),
        ]
    )
    comparison = compact_overlap(details)["comparisons"][0]
    assert comparison["overlap_level"] == level
    assert comparison["indicator"] == indicator


def test_compact_summary_is_ranked_truncated_and_ready_to_display():
    details = calculate_overlap(
        [
            portfolio(CODES[0], [(ISIN, 8, 1), (OTHER, 4, 1), (FOURTH, 3, 1)]),
            portfolio(CODES[1], [(ISIN, 5, 1), (OTHER, 2, 1), (THIRD, 7, 1)]),
        ]
    )
    compact = compact_overlap(details, max_common_items=1, max_unique_items=1)
    comparison = compact["comparisons"][0]
    assert comparison["title"] == (
        "Parag Parikh Flexi Cap vs Parag Parikh ELSS Tax Saver"
    )
    assert comparison["portfolio_overlap_pct"] == 7
    assert comparison["common_security_count"] == 2
    assert len(comparison["top_common_holdings"]) == 1
    assert comparison["top_common_holdings"][0]["overlap_weight_pct"] == 5
    assert comparison["unique_holdings"][0]["unique_security_count"] == 1
    assert len(comparison["unique_holdings"][0]["top_unique_holdings"]) == 1
    assert "Portfolio overlap: 7.00%  🟢 Low" in compact["summary_text"]
    assert "2 common securities" in compact["summary_text"]
    assert "Top common holdings" in compact["summary_text"]
    assert "Key differences" in compact["summary_text"]
    assert "Interpretation:" in compact["summary_text"]


@pytest.mark.parametrize("limit", [0, 26, True, 1.5, "10"])
def test_compact_summary_validates_item_limit(limit):
    details = calculate_overlap([portfolio(CODES[0], []), portfolio(CODES[1], [])])
    with pytest.raises(FundError) as error:
        compact_overlap(details, limit)
    assert error.value.code == "INVALID_LIMIT"


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
    assert "summary_text" in result["compact_summary"]
    assert "details" not in result
    assert svc.provider.downloads == 2
    assert all(f["source"] and f["retrieved_at"] for f in result["funds"])
    svc.provider.disclosures = lambda: pytest.fail(
        "Explicit cached month should work offline"
    )
    svc.compare_fund_overlap(CODES[:2], "2026-07")


def test_service_can_include_full_details(tmp_path):
    data = {(code, "2026-08"): portfolio(code, [(ISIN, 5, 1)]) for code in CODES[:2]}
    result = service(tmp_path, data).compare_fund_overlap(
        CODES[:2],
        "2026-08",
        max_common_items=3,
        max_unique_items=2,
        include_details=True,
    )
    assert result["compact_summary"]["items_shown"] == {
        "common": 3,
        "unique_per_fund": 2,
    }
    assert result["details"]["pairwise"][0]["weighted_overlap_pct"] == 5


def test_service_rejects_invalid_unique_limit(tmp_path):
    svc = service(tmp_path, {})
    with pytest.raises(FundError) as error:
        svc.compare_fund_overlap(CODES[:2], "2026-08", max_unique_items=0)
    assert error.value.code == "INVALID_LIMIT"


def test_service_rejects_invalid_detail_option(tmp_path):
    svc = service(tmp_path, {})
    svc.provider.disclosures = lambda: pytest.fail("Invalid input must not fetch")
    with pytest.raises(FundError) as error:
        svc.compare_fund_overlap(CODES[:2], include_details="yes")
    assert error.value.code == "INVALID_DETAIL_OPTION"


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
            comparison = payload["compact_summary"]["comparisons"][0]
            assert comparison["portfolio_overlap_pct"] == 7
            assert "details" not in payload
            detailed = await client.call_tool(
                "compare_fund_overlap",
                {
                    "scheme_codes": CODES[:2],
                    "month": "2026-08",
                    "include_details": True,
                },
            )
            detailed_payload = json.loads(detailed.content[0].text)
            assert (
                detailed_payload["details"]["pairwise"][0]["weighted_overlap_pct"] == 7
            )
            result = await client.call_tool(
                "compare_fund_overlap", {"scheme_codes": [CODES[0], "118955"]}
            )
            assert (
                json.loads(result.content[0].text)["error"]["code"]
                == "UNSUPPORTED_HOLDINGS_SCHEME"
            )

    asyncio.run(call())
