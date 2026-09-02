from __future__ import annotations

import math
import statistics

from models.schemas import NavPoint
from services.errors import FundError


def calculate_metrics(points: list[NavPoint]) -> dict[str, float]:
    """Calculate return and risk metrics from chronological NAV observations."""
    normalized = sorted(points, key=lambda point: point.date)
    if len(normalized) < 2:
        raise FundError("NO_NAV_DATA", "At least two NAV observations are required.")
    if any(point.nav <= 0 or not math.isfinite(point.nav) for point in normalized):
        raise FundError("CALCULATION_ERROR", "NAV observations must be finite and positive.")

    start, end = normalized[0], normalized[-1]
    days = (end.date - start.date).days
    if days <= 0:
        raise FundError("CALCULATION_ERROR", "NAV observations must span multiple dates.")

    daily_returns = [
        current.nav / previous.nav - 1
        for previous, current in zip(normalized, normalized[1:])
    ]
    volatility = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 0.0

    peak = normalized[0].nav
    max_drawdown = 0.0
    for point in normalized:
        peak = max(peak, point.nav)
        max_drawdown = min(max_drawdown, (point.nav - peak) / peak)

    years = days / 365.2425
    return {
        "absolute_return_pct": round((end.nav / start.nav - 1) * 100, 4),
        "cagr_pct": round(((end.nav / start.nav) ** (1 / years) - 1) * 100, 4),
        "annualized_volatility_pct": round(volatility * math.sqrt(252) * 100, 4),
        "max_drawdown_pct": round(max_drawdown * 100, 4),
    }

