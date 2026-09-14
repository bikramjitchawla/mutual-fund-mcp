import copy
import io
import sqlite3

import pytest
from openpyxl import Workbook

from clients.ppfas import (
    FUNDS,
    INDEX,
    SCOPE,
    PPFASProvider,
    month_end,
    parse_workbook,
    validate_isin,
)
from services.errors import FundError
from services.holdings import HoldingsService
from services.holdings_store import HoldingsStore

ISIN = "INE040A01034"
OTHER = "INE090A01021"


def workbook_bytes(*, date_text="August 31, 2026", bad_isin=False, total=True):
    book = Workbook()
    sheet = book.active
    sheet.title = "PPFCF"
    sheet.append([None, "Parag Parikh Flexi Cap Fund"])
    sheet.append([None, f"Monthly Portfolio Statement as on {date_text}"])
    sheet.append(
        [
            None,
            "Name of the Instrument",
            "ISIN",
            "Industry / Rating",
            "Quantity",
            "Market/Fair Value (Rs. in Lakhs)",
            "% to Net Assets",
        ]
    )
    sheet.append(
        [None, "HDFC Bank", "INVALID" if bad_isin else ISIN, "Banks", 100, 2, 0.08]
    )
    sheet.cell(4, 7).number_format = "0.00%"
    sheet.append([None, "HDFC Bank", ISIN, "Banks", 50, 1, "4.00%"])
    sheet.append([None, "ICICI Bank", OTHER, "Banks", 1, 0.001, "$0.00%"])
    sheet.append([None, "Cash", None, None, None, 10, 0.5])
    if total:
        sheet.append([None, "GRAND TOTAL", None, None, None, 13, 1])
    sheet.append([None, "Derivatives", "NOT AN ISIN", None, None, -20, -0.1])
    output = io.BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def test_parser_converts_units_aggregates_isin_and_excludes_cash_derivatives():
    result = parse_workbook(
        workbook_bytes(), "122639", "2026-08", "https://amc.ppfas.com/example"
    )
    assert len(result["holdings"]) == 2
    first = result["holdings"][0]
    assert first["quantity"] == 150
    assert first["market_value"] == 300000
    assert first["portfolio_weight_pct"] == 12
    assert result["holdings"][1]["portfolio_weight_pct"] == 0


@pytest.mark.parametrize(
    "kwargs", [{"date_text": "July 31, 2026"}, {"bad_isin": True}, {"total": False}]
)
def test_parser_rejects_wrong_dates_bad_isins_and_incomplete_files(kwargs):
    with pytest.raises(FundError) as error:
        parse_workbook(workbook_bytes(**kwargs), "122639", "2026-08", "test")
    assert error.value.code == "INVALID_PROVIDER_RESPONSE"


def test_parser_rejects_non_workbook():
    with pytest.raises(FundError):
        parse_workbook(b"html", "122639", "2026-08", "test")


def test_disclosure_discovery_restricts_hosts_and_scheme_mapping():
    calls = []

    def fetch(url):
        calls.append(url)
        return b"""<a href="/downloads/portfolio-disclosure/2026/PPFCF_PPFAS_Monthly_Portfolio_Report_August_31_2026.xlsx?revision=2">file</a>
        <a href="https://evil.example/downloads/portfolio-disclosure/2026/PPLF_PPFAS_Monthly_Portfolio_Report_August_31_2026.xlsx">bad</a>"""

    provider = PPFASProvider(fetch)
    assert list(provider.disclosures()) == [("122639", "2026-08")]
    assert provider.disclosures()[("122639", "2026-08")].endswith("?revision=2")
    assert calls == [INDEX]
    with pytest.raises(FundError):
        provider.get_snapshot("122639", "2026-08", "https://evil.example")


@pytest.mark.parametrize("value", ["invalid", "INE040A01035", "' OR 1=1 --"])
def test_isin_validation(value):
    with pytest.raises(FundError) as error:
        validate_isin(value)
    assert error.value.code == "INVALID_ISIN"


def test_isin_normalizes_case_and_space():
    assert validate_isin(" ine040a01034 ") == ISIN


@pytest.mark.parametrize("value", ["2026-13", "2026-8", "bad", "0000-01"])
def test_month_validation(value):
    with pytest.raises(FundError):
        month_end(value)


def snapshot(code, month, quantity=100, weight=10):
    return {
        "scheme_code": code,
        "scheme_name": FUNDS[code][1],
        "portfolio_date": month_end(month).isoformat(),
        "source": "https://amc.ppfas.com/test",
        "scope": SCOPE,
        "holdings": [
            {
                "isin": ISIN if quantity else OTHER,
                "security_name": "HDFC Bank" if quantity else "ICICI Bank",
                "sector": "Banks",
                "quantity": quantity or 1,
                "market_value": 1000,
                "portfolio_weight_pct": weight,
            }
        ],
    }


def test_store_survives_reopen_and_replaces_snapshot_atomically(tmp_path):
    path = str(tmp_path / "data" / "holdings.sqlite")
    store = HoldingsStore(path)
    original = snapshot("122639", "2026-08")
    store.save(original)
    assert (
        HoldingsStore(path).get("122639", "2026-08-31")["holdings"][0]["quantity"]
        == 100
    )
    broken = copy.deepcopy(original)
    broken["holdings"].append(broken["holdings"][0])
    with pytest.raises(sqlite3.IntegrityError):
        store.save(broken)
    assert store.get("122639", "2026-08-31")["holdings"][0]["quantity"] == 100
    updated = snapshot("122639", "2026-08", 200)
    store.save(updated)
    assert store.get("122639", "2026-08-31")["holdings"][0]["quantity"] == 200


class Provider:
    def __init__(self, snapshots):
        self.snapshots = snapshots
        self.downloads = 0

    def disclosures(self):
        return {key: "https://amc.ppfas.com/test" for key in self.snapshots}

    def get_snapshot(self, code, month, url):
        self.downloads += 1
        return copy.deepcopy(self.snapshots[(code, month)])


def service(tmp_path, snapshots):
    provider = Provider(snapshots)
    return HoldingsService(provider, HoldingsStore(str(tmp_path / "holdings.sqlite")))


def test_lookup_ranks_weights_exposes_partial_coverage_and_uses_cache(tmp_path):
    svc = service(
        tmp_path,
        {
            (code, "2026-08"): snapshot(code, "2026-08", weight=weight)
            for code, weight in [("122639", 5), ("147481", 10)]
        },
    )
    result = svc.get_funds_holding_stock(ISIN)
    assert [f["scheme_code"] for f in result["funds"]] == ["147481", "122639"]
    assert result["coverage"]["all_amcs"] is False
    assert result["coverage"]["complete_within_supported_scope"] is False
    assert len(result["coverage"]["unavailable_funds"]) == 2
    assert result["data_as_of"] == "2026-08-31"
    svc.get_funds_holding_stock(ISIN, "2026-08")
    assert svc.provider.downloads == 2


def test_missing_security_is_empty_with_coverage(tmp_path):
    svc = service(
        tmp_path, {("122639", "2026-08"): snapshot("122639", "2026-08", quantity=0)}
    )
    result = svc.get_funds_holding_stock(ISIN)
    assert result["funds"] == []
    assert result["coverage"]["covered_scheme_codes"] == ["122639"]


def test_changes_identify_buyer_increase_reduction_exit(tmp_path):
    quantities = {
        "122639": (0, 100),
        "143269": (100, 200),
        "147481": (100, 50),
        "148958": (100, 0),
    }
    snapshots = {
        (code, month): snapshot(code, month, pair[i])
        for code, pair in quantities.items()
        for i, month in enumerate(["2026-07", "2026-08"])
    }
    svc = service(tmp_path, snapshots)
    result = svc.get_stock_ownership_changes(ISIN, "2026-07", "2026-08")
    for key in [
        "new_fund_buyers",
        "funds_increasing_position",
        "funds_reducing_position",
        "funds_exiting_position",
    ]:
        assert result[key] == 1
    assert (
        svc.get_new_fund_buyers(ISIN, "2026-08")["changes"][0]["scheme_code"]
        == "122639"
    )
    assert (
        svc.get_funds_accumulating_stock(ISIN, "2026-08")["changes"][0]["scheme_code"]
        == "143269"
    )
    assert (
        svc.get_fund_exits_from_stock(ISIN, "2026-08")["changes"][0]["scheme_code"]
        == "148958"
    )


def test_missing_snapshot_never_counts_as_exit(tmp_path):
    snapshots = {
        ("122639", "2026-07"): snapshot("122639", "2026-07"),
        ("147481", "2026-07"): snapshot("147481", "2026-07"),
        ("147481", "2026-08"): snapshot("147481", "2026-08"),
    }
    svc = service(tmp_path, snapshots)
    result = svc.get_stock_ownership_changes(ISIN, "2026-07", "2026-08")
    assert result["funds_exiting_position"] == 0
    assert "122639" in result["coverage"]["excluded_scheme_codes"]


def test_get_fund_rejects_unsupported_and_reads_cached_month_offline(tmp_path):
    svc = service(tmp_path, {("122639", "2026-08"): snapshot("122639", "2026-08")})
    with pytest.raises(FundError) as error:
        svc.get_fund_holdings("118955")
    assert error.value.code == "UNSUPPORTED_HOLDINGS_SCHEME"
    svc.get_fund_holdings("122639", "2026-08")
    svc.provider.disclosures = lambda: pytest.fail(
        "Cached snapshot should work offline"
    )
    assert svc.get_fund_holdings("122639", "2026-08")["data_as_of"] == "2026-08-31"
