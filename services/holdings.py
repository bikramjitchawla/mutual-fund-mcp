"""Coverage-aware holdings queries and matched-snapshot ownership comparisons."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from clients.ppfas import FUNDS, SCOPE, month_end, validate_isin
from services.errors import FundError
from services.mutual_funds import MAX_COMPARE_FUNDS, MutualFundService
from services.overlap import calculate_overlap


class HoldingsService:
    def __init__(self, provider, store):
        self.provider = provider
        self.store = store

    def _snapshot(self, code: str, month: str, refresh: bool = False) -> dict:
        if code not in FUNDS:
            raise FundError(
                "UNSUPPORTED_HOLDINGS_SCHEME",
                "Use get_holdings_coverage for supported PPFAS Direct Growth codes.",
            )
        day = month_end(month).isoformat()
        if not refresh:
            cached = self.store.get(code, day)
            if cached is not None:
                return cached
        url = self.provider.disclosures().get((code, month))
        if url is None:
            raise FundError(
                "NO_HOLDINGS_DATA",
                "No supported XLSX disclosure for this scheme and month.",
            )
        snapshot = self.provider.get_snapshot(code, month, url)
        self.store.save(snapshot)
        return self.store.get(code, day)

    def _month(self, month: str | None) -> str:
        if month is not None:
            month_end(month)
            return month
        return max(m for _, m in self.provider.disclosures())

    def get_holdings_coverage(self) -> dict:
        links = self.provider.disclosures()
        return {
            "scope": SCOPE,
            "funds": [
                {
                    "scheme_code": code,
                    "scheme_name": name,
                    "available_months": sorted(m for c, m in links if c == code),
                }
                for code, (_, name) in FUNDS.items()
            ],
            "source": "https://amc.ppfas.com/downloads/portfolio-disclosure/index.php",
            "retrieved_at": MutualFundService._now(),
        }

    def get_fund_holdings(self, scheme_code: str, month: str | None = None) -> dict:
        if scheme_code not in FUNDS:
            raise FundError(
                "UNSUPPORTED_HOLDINGS_SCHEME",
                "Use get_holdings_coverage for supported PPFAS Direct Growth codes.",
            )
        if month is None:
            months = [m for c, m in self.provider.disclosures() if c == scheme_code]
            if not months:
                raise FundError(
                    "NO_HOLDINGS_DATA", "No disclosures available for this scheme."
                )
            month = max(months)
        snapshot = self._snapshot(scheme_code, month)
        return {
            **snapshot,
            "data_as_of": snapshot["portfolio_date"],
            "market_value_currency": "INR",
            "reported_weight_sum_pct": round(
                sum(h["portfolio_weight_pct"] for h in snapshot["holdings"]), 4
            ),
        }

    def compare_fund_overlap(
        self, scheme_codes: list[str], month: str | None = None
    ) -> dict:
        codes = list(dict.fromkeys(scheme_codes))
        if not 2 <= len(codes) <= MAX_COMPARE_FUNDS:
            raise FundError(
                "INVALID_COMPARISON",
                f"Overlap requires 2 to {MAX_COMPARE_FUNDS} distinct scheme codes.",
            )
        if any(code not in FUNDS for code in codes):
            raise FundError(
                "UNSUPPORTED_HOLDINGS_SCHEME",
                "Overlap supports only covered PPFAS schemes; use get_holdings_coverage.",
            )
        if month is None:
            links = self.provider.disclosures()
            common_months = set.intersection(
                *({m for c, m in links if c == code} for code in codes)
            )
            if not common_months:
                raise FundError(
                    "NO_HOLDINGS_DATA",
                    "No common disclosure month exists for the selected funds.",
                )
            month = max(common_months)
        day = month_end(month).isoformat()
        # All requested snapshots must succeed. Never compare a silently reduced subset.
        with ThreadPoolExecutor(max_workers=min(4, len(codes))) as pool:
            snapshots = list(pool.map(lambda code: self._snapshot(code, month), codes))
        return {
            "month": month,
            "data_as_of": day,
            **calculate_overlap(snapshots),
            "coverage": {
                "scope": SCOPE,
                "requested_scheme_codes": codes,
                "compared_scheme_codes": codes,
                "complete_for_requested_funds": True,
                "all_amcs": False,
            },
            "retrieved_at": MutualFundService._now(),
        }

    def _load_month(self, month: str) -> tuple[dict, list]:
        def load(code):
            try:
                return code, self._snapshot(code, month), None
            except FundError as error:
                return (
                    code,
                    None,
                    {"scheme_code": code, "code": error.code, "message": error.message},
                )

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(load, FUNDS))
        snapshots = {
            code: snapshot for code, snapshot, error in results if snapshot is not None
        }
        failures = [error for code, snapshot, error in results if error is not None]
        if not snapshots:
            raise FundError(
                "NO_HOLDINGS_DATA",
                "No covered fund snapshots could be loaded for this month; check provider availability or get_holdings_coverage.",
            )
        return snapshots, failures

    @staticmethod
    def _coverage(snapshots: dict, failures: list) -> dict:
        return {
            "scope": SCOPE,
            "covered_scheme_codes": sorted(snapshots),
            "unavailable_funds": failures,
            "complete_within_supported_scope": not failures,
            "all_amcs": False,
        }

    def get_funds_holding_stock(self, isin: str, month: str | None = None) -> dict:
        isin = validate_isin(isin)
        month = self._month(month)
        snapshots, failures = self._load_month(month)
        funds = []
        security = {"isin": isin, "name": None}
        for code, snapshot in snapshots.items():
            for holding in snapshot["holdings"]:
                if holding["isin"] == isin and holding["quantity"] > 0:
                    security["name"] = holding["security_name"]
                    funds.append(
                        {
                            "scheme_code": code,
                            "scheme_name": snapshot["scheme_name"],
                            **holding,
                            "portfolio_date": snapshot["portfolio_date"],
                            "source": snapshot["source"],
                            "retrieved_at": snapshot["retrieved_at"],
                        }
                    )
        return {
            "security": security,
            "funds": sorted(
                funds, key=lambda f: (-f["portfolio_weight_pct"], f["scheme_code"])
            ),
            "data_as_of": month_end(month).isoformat(),
            "coverage": self._coverage(snapshots, failures),
            "retrieved_at": MutualFundService._now(),
        }

    def get_stock_ownership_changes(
        self, isin: str, from_month: str, to_month: str
    ) -> dict:
        isin = validate_isin(isin)
        if month_end(from_month) >= month_end(to_month):
            raise FundError("INVALID_MONTH", "from_month must precede to_month.")
        before, before_errors = self._load_month(from_month)
        after, after_errors = self._load_month(to_month)
        matched = sorted(before.keys() & after.keys())
        if not matched:
            raise FundError(
                "INSUFFICIENT_OVERLAP", "No funds have snapshots for both months."
            )
        changes = []
        for code in matched:
            old = next((h for h in before[code]["holdings"] if h["isin"] == isin), None)
            new = next((h for h in after[code]["holdings"] if h["isin"] == isin), None)
            old_qty, new_qty = (
                (old["quantity"] if old else 0),
                (new["quantity"] if new else 0),
            )
            if old_qty == new_qty == 0:
                continue
            status = (
                "new_buyer"
                if old_qty == 0
                else "exit"
                if new_qty == 0
                else "increased"
                if new_qty > old_qty
                else "reduced"
                if new_qty < old_qty
                else "unchanged"
            )
            changes.append(
                {
                    "scheme_code": code,
                    "scheme_name": after[code]["scheme_name"],
                    "status": status,
                    "quantity_from": old_qty,
                    "quantity_to": new_qty,
                    "quantity_change": new_qty - old_qty,
                    "weight_from_pct": old["portfolio_weight_pct"] if old else 0,
                    "weight_to_pct": new["portfolio_weight_pct"] if new else 0,
                    "sources": [before[code]["source"], after[code]["source"]],
                }
            )
        return {
            "isin": isin,
            "from_month": from_month,
            "to_month": to_month,
            "new_fund_buyers": sum(c["status"] == "new_buyer" for c in changes),
            "funds_increasing_position": sum(
                c["status"] == "increased" for c in changes
            ),
            "funds_reducing_position": sum(c["status"] == "reduced" for c in changes),
            "funds_exiting_position": sum(c["status"] == "exit" for c in changes),
            "changes": changes,
            "coverage": {
                "scope": SCOPE,
                "matched_scheme_codes": matched,
                "excluded_scheme_codes": sorted(set(FUNDS) - set(matched)),
                "from_month_errors": before_errors,
                "to_month_errors": after_errors,
                "all_amcs": False,
            },
            "method": "Quantity changes only across matched complete ISIN-security snapshots. Missing snapshots never imply exits. Corporate actions, splits, mergers and arbitrage can change quantities; these are not verified trading flows.",
            "data_as_of": month_end(to_month).isoformat(),
            "retrieved_at": MutualFundService._now(),
        }

    def _monthly_changes(self, isin: str, month: str, status: str) -> dict:
        day = month_end(month)
        if day.year == 1 and day.month == 1:
            raise FundError("INVALID_MONTH", "No preceding month exists.")
        previous = f"{day.year - (day.month == 1):04d}-{12 if day.month == 1 else day.month - 1:02d}"
        result = self.get_stock_ownership_changes(isin, previous, month)
        result["changes"] = [c for c in result["changes"] if c["status"] == status]
        result["filter"] = status
        return result

    def get_funds_accumulating_stock(self, isin: str, month: str) -> dict:
        return self._monthly_changes(isin, month, "increased")

    def get_new_fund_buyers(self, isin: str, month: str) -> dict:
        return self._monthly_changes(isin, month, "new_buyer")

    def get_fund_exits_from_stock(self, isin: str, month: str) -> dict:
        return self._monthly_changes(isin, month, "exit")
