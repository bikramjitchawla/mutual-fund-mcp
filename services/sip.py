"""Monthly SIP simulation with deterministic ACT/365 money-weighted returns."""

from __future__ import annotations

import calendar
import math
from bisect import bisect_left
from datetime import date

from models.schemas import NavPoint
from services.advanced_analytics import normalize_nav_points
from services.errors import FundError

SIP_METHOD = {
    "schedule": "Monthly from from_date inclusive to to_date exclusive; original day clamped to each month's last day",
    "execution": "First available NAV on/after each scheduled date, no later than to_date",
    "valuation": "Last available NAV on/before to_date; installments without an eligible NAV remain unfilled",
    "xirr": "ACT/365 on actual execution dates; negative contributions and one positive terminal valuation; null when undefined or outside solver bounds",
    "costs": "No taxes, loads or transaction charges modeled",
}


def validate_amount(amount: float) -> None:
    if (
        isinstance(amount, bool)
        or not isinstance(amount, (int, float))
        or not math.isfinite(amount)
        or amount <= 0
    ):
        raise FundError("INVALID_AMOUNT", "monthly_amount must be finite and positive.")


def _xirr_pct(
    deposits: list[tuple[date, float]], valuation_date: date, value: float
) -> float | None:
    """Solve sum(deposit * (1+r)**years) = value in log space.

    All deposits are positive and occur on/before valuation. Thus the equation
    is monotone, with a unique root when at least one deposit precedes valuation
    and terminal value exceeds same-day deposits. Bounds use log(1+r).
    """
    if not any(day < valuation_date for day, _ in deposits):
        return None
    if value <= math.fsum(amount for day, amount in deposits if day == valuation_date):
        return None
    terms = [
        (math.log(amount), (valuation_date - day).days / 365)
        for day, amount in deposits
    ]
    log_value = math.log(value)

    def residual(log_rate: float) -> float:
        logs = [log_amount + years * log_rate for log_amount, years in terms]
        offset = max(logs)
        return offset + math.log(math.fsum(math.exp(x - offset) for x in logs)) - log_value

    low, high = -700.0, 700.0
    if residual(low) > 0 or residual(high) < 0:
        return None
    for _ in range(200):
        middle = (low + high) / 2
        if residual(middle) < 0:
            low = middle
        else:
            high = middle
    return round(math.expm1((low + high) / 2) * 100, 4)


def calculate_sip(
    points: list[NavPoint], monthly_amount: float, start: date, end: date
) -> dict:
    """Buy on monthly dates in [start, end) and value at the last NAV <= end."""
    validate_amount(monthly_amount)
    if start >= end:
        raise FundError("INVALID_DATE_RANGE", "SIP from_date must be before to_date.")
    points = normalize_nav_points([point for point in points if start <= point.date <= end])
    dates = [point.date for point in points]
    details = []
    unfilled = []
    deposits = []
    month_index = start.year * 12 + start.month - 1
    while month_index < 10000 * 12:
        year, month_zero = divmod(month_index, 12)
        month = month_zero + 1
        scheduled = date(year, month, min(start.day, calendar.monthrange(year, month)[1]))
        if scheduled >= end:
            break
        index = bisect_left(dates, scheduled)
        if index == len(points):
            unfilled.append(scheduled.isoformat())
        else:
            point = points[index]
            units = monthly_amount / point.nav
            if not math.isfinite(units) or units <= 0:
                raise FundError("CALCULATION_ERROR", "SIP units exceed numerical limits.")
            details.append({
                "scheduled_date": scheduled.isoformat(),
                "investment_date": point.date.isoformat(),
                "amount": monthly_amount,
                "nav": point.nav,
                "units": units,
            })
            deposits.append((point.date, monthly_amount))
        month_index += 1

    if not details:
        raise FundError("NO_NAV_DATA", "No SIP installments can be valued in this period.")
    try:
        units = math.fsum(item["units"] for item in details)
        invested = monthly_amount * len(details)
        value = units * points[-1].nav
        gain = (value / invested - 1) * 100
        if not all(math.isfinite(number) for number in (units, invested, value, gain)) or value <= 0:
            raise OverflowError
    except (OverflowError, ZeroDivisionError) as error:
        raise FundError("CALCULATION_ERROR", "SIP results exceed numerical limits.") from error
    xirr = _xirr_pct(deposits, points[-1].date, value)
    return {
        "monthly_amount": monthly_amount,
        "scheduled_installments": len(details) + len(unfilled),
        "installments": len(details),
        "unfilled_installment_dates": unfilled,
        "total_invested": round(invested, 2),
        "total_units": round(units, 8),
        "ending_nav": points[-1].nav,
        "current_value": round(value, 2),
        "profit": round(value - invested, 2),
        "absolute_gain_pct": round(gain, 4),
        "xirr_pct": xirr,
        "xirr_status": "calculated" if xirr is not None else "undefined_or_out_of_bounds",
        "installment_details": details,
        "observation_period": {"from": points[0].date.isoformat(), "to": points[-1].date.isoformat()},
        "data_as_of": points[-1].date.isoformat(),
    }
