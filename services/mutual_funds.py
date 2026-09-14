from __future__ import annotations

from datetime import date, datetime, timezone

from clients.base import MutualFundProvider
from services.advanced_analytics import (
    advanced_metrics,
    normalize_nav_points,
    rolling_returns,
)
from services.analytics import calculate_metrics
from services.errors import FundError
from services.sip import SIP_METHOD, calculate_sip, validate_amount

MAX_RANGE_DAYS = 366 * 5
MAX_COMPARE_FUNDS = 10


class MutualFundService:
    def __init__(self, provider: MutualFundProvider) -> None:
        self.provider = provider

    def search_funds(self, query: str) -> dict:
        schemes = self.provider.search_funds(query)
        return {
            "results": [
                {
                    "scheme_code": scheme.scheme_code,
                    "scheme_name": scheme.scheme_name,
                    "fund_house": scheme.fund_house,
                }
                for scheme in schemes
            ],
            "source": self.provider.source,
            "retrieved_at": self._now(),
        }

    def get_latest_nav(self, scheme_code: str) -> dict:
        scheme, point = self.provider.get_latest_nav(scheme_code)
        return {
            "scheme_code": scheme.scheme_code,
            "scheme_name": scheme.scheme_name,
            "nav": point.nav,
            "nav_date": point.date.isoformat(),
            "source": self.provider.source,
            "data_as_of": point.date.isoformat(),
            "retrieved_at": self._now(),
        }

    def get_nav_history(self, scheme_code: str, from_date: str, to_date: str) -> dict:
        start, end = self._date_range(from_date, to_date)
        scheme, points = self.provider.get_nav_history(scheme_code, start, end)
        return {
            "scheme_code": scheme.scheme_code,
            "scheme_name": scheme.scheme_name,
            "from_date": start.isoformat(),
            "to_date": end.isoformat(),
            "data": [
                {"date": point.date.isoformat(), "nav": point.nav} for point in points
            ],
            "source": self.provider.source,
            "data_as_of": points[-1].date.isoformat(),
            "retrieved_at": self._now(),
        }

    def calculate_fund_metrics(
        self, scheme_code: str, from_date: str, to_date: str
    ) -> dict:
        start, end = self._date_range(from_date, to_date)
        scheme, points = self.provider.get_nav_history(scheme_code, start, end)
        return {
            "scheme_code": scheme.scheme_code,
            "scheme_name": scheme.scheme_name,
            "period": {"from": start.isoformat(), "to": end.isoformat()},
            "observation_period": {
                "from": points[0].date.isoformat(),
                "to": points[-1].date.isoformat(),
            },
            "metrics": calculate_metrics(points),
            "volatility_method": "sample standard deviation of successive NAV returns, annualized using sqrt(252)",
            "source": self.provider.source,
            "data_as_of": points[-1].date.isoformat(),
            "retrieved_at": self._now(),
        }

    def compare_funds(
        self, scheme_codes: list[str], from_date: str, to_date: str
    ) -> dict:
        start, end = self._date_range(from_date, to_date)
        codes = list(dict.fromkeys(scheme_codes))
        if not 2 <= len(codes) <= MAX_COMPARE_FUNDS:
            raise FundError(
                "INVALID_COMPARISON",
                f"Comparison requires 2 to {MAX_COMPARE_FUNDS} distinct scheme codes.",
            )
        funds = []
        data_dates = []
        for code in codes:
            scheme, points = self.provider.get_nav_history(code, start, end)
            points = normalize_nav_points(points)
            metrics = advanced_metrics(points)
            funds.append(
                {
                    "scheme_code": scheme.scheme_code,
                    "scheme_name": scheme.scheme_name,
                    **metrics,
                    "volatility_pct": metrics["annualized_volatility_pct"],
                    "observation_from": points[0].date.isoformat(),
                    "observation_to": points[-1].date.isoformat(),
                }
            )
            data_dates.append(points[-1].date)
        return {
            "period": {"from": start.isoformat(), "to": end.isoformat()},
            "funds": funds,
            "advanced_metrics_method": {
                "rolling_returns": "Calendar 1Y/3Y windows starting at each NAV; first NAV on/after anniversary; actual-day CAGR using 365.2425 days/year",
                "downside_volatility": "sqrt(mean(min(successive NAV return, 0)^2)) * sqrt(252); includes all returns in denominator",
                "sortino_ratio": "CAGR / annualized downside volatility; minimum acceptable return = 0",
                "calmar_ratio": "CAGR / abs(maximum drawdown) over the observation period",
                "max_drawdown_duration_days": "Longest peak-to-recovery episode in calendar days; ongoing episodes end at last observation",
                "recovery_days": "First deepest drawdown trough to recovery of its prior peak; null if unrecovered or no drawdown",
            },
            "volatility_method": "sample standard deviation of successive NAV returns, annualized using sqrt(252)",
            "source": self.provider.source,
            "data_as_of": min(data_dates).isoformat(),
            "retrieved_at": self._now(),
        }

    def calculate_rolling_returns(
        self, scheme_code: str, from_date: str, to_date: str
    ) -> dict:
        start, end = self._date_range(from_date, to_date)
        scheme, points = self.provider.get_nav_history(scheme_code, start, end)
        points = normalize_nav_points([p for p in points if start <= p.date <= end])
        return {
            "scheme_code": scheme.scheme_code,
            "scheme_name": scheme.scheme_name,
            "period": {"from": from_date, "to": to_date},
            "rolling_returns": rolling_returns(points),
            "method": "Calendar 1Y/3Y windows ending at first NAV on/after anniversary; actual-day CAGR using 365.2425 days/year. Incomplete windows excluded.",
            "source": self.provider.source,
            "data_as_of": points[-1].date.isoformat(),
            "retrieved_at": self._now(),
        }

    def calculate_sip_returns(
        self, scheme_code: str, monthly_amount: float, from_date: str, to_date: str
    ) -> dict:
        start, end = self._date_range(from_date, to_date)
        validate_amount(monthly_amount)
        if start == end:
            raise FundError(
                "INVALID_DATE_RANGE", "SIP from_date must be before to_date."
            )
        scheme, points = self.provider.get_nav_history(scheme_code, start, end)
        return {
            "scheme_code": scheme.scheme_code,
            "scheme_name": scheme.scheme_name,
            "period": {"from": start.isoformat(), "to": end.isoformat()},
            **calculate_sip(points, monthly_amount, start, end),
            "method": dict(SIP_METHOD),
            "source": self.provider.source,
            "retrieved_at": self._now(),
        }

    def compare_sip_returns(
        self,
        scheme_codes: list[str],
        monthly_amount: float,
        from_date: str,
        to_date: str,
    ) -> dict:
        start, end = self._date_range(from_date, to_date)
        validate_amount(monthly_amount)
        codes = list(dict.fromkeys(scheme_codes))
        if not 2 <= len(codes) <= MAX_COMPARE_FUNDS:
            raise FundError(
                "INVALID_COMPARISON",
                f"Comparison requires 2 to {MAX_COMPARE_FUNDS} distinct scheme codes.",
            )
        funds = [
            self.calculate_sip_returns(code, monthly_amount, from_date, to_date)
            for code in codes
        ]
        return {
            "period": {"from": start.isoformat(), "to": end.isoformat()},
            "monthly_amount": monthly_amount,
            "funds": funds,
            "source": self.provider.source,
            "data_as_of": min(fund["data_as_of"] for fund in funds),
            "retrieved_at": self._now(),
        }

    @staticmethod
    def _date_range(from_date: str, to_date: str) -> tuple[date, date]:
        try:
            start = date.fromisoformat(from_date)
            end = date.fromisoformat(to_date)
        except (TypeError, ValueError) as error:
            raise FundError(
                "INVALID_DATE_RANGE", "Dates must use YYYY-MM-DD format."
            ) from error
        if start > end:
            raise FundError(
                "INVALID_DATE_RANGE", "from_date must not be after to_date."
            )
        if (end - start).days > MAX_RANGE_DAYS:
            raise FundError(
                "INVALID_DATE_RANGE", "Date range cannot exceed five years."
            )
        return start, end

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
