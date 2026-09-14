"""Deterministic NAV analytics; conventions are documented in README.md."""

from __future__ import annotations

import calendar
import math
from bisect import bisect_left

from models.schemas import NavPoint
from services.analytics import calculate_metrics
from services.errors import FundError


def normalize_nav_points(points: list[NavPoint]) -> list[NavPoint]:
    """Validate NAV values and reject ambiguous duplicate observation dates."""
    points = sorted(points, key=lambda p: p.date)
    if not points:
        raise FundError("NO_NAV_DATA", "No NAV observations are available.")
    if any(not math.isfinite(p.nav) or p.nav <= 0 for p in points):
        raise FundError("CALCULATION_ERROR", "NAV observations must be finite and positive.")
    if len({p.date for p in points}) != len(points):
        raise FundError("CALCULATION_ERROR", "NAV dates must be unique.")
    return points


def rolling_returns(points: list[NavPoint]) -> dict:
    """Calculate full calendar windows without fetching outside the input history."""
    points = normalize_nav_points(points)
    dates = [p.date for p in points]
    result = {}
    for years in (1, 3):
        windows = []
        values = []
        for start in points:
            if start.date.year + years > 9999:
                continue
            target_year = start.date.year + years
            last_day = calendar.monthrange(target_year, start.date.month)[1]
            anniversary = start.date.replace(
                year=target_year, day=min(start.date.day, last_day)
            )
            index = bisect_left(dates, anniversary)
            if index == len(points):
                continue
            end = points[index]
            elapsed_days = (end.date - start.date).days
            value = ((end.nav / start.nav) ** (365.2425 / elapsed_days) - 1) * 100
            values.append(value)
            windows.append({
                "from": start.date.isoformat(),
                "to": end.date.isoformat(),
                "return_pct": round(value, 4),
            })
        result[f"{years}y"] = {
            "count": len(values),
            "average_pct": round(math.fsum(values) / len(values), 4) if values else None,
            "best_pct": round(max(values), 4) if values else None,
            "worst_pct": round(min(values), 4) if values else None,
            "windows": windows,
        }
    return result


def advanced_metrics(points: list[NavPoint]) -> dict:
    """Extend base metrics using a zero minimum acceptable return for Sortino."""
    points = normalize_nav_points(points)
    metrics = calculate_metrics(points)
    returns = [b.nav / a.nav - 1 for a, b in zip(points, points[1:])]
    downside = math.sqrt(math.fsum(min(r, 0) ** 2 for r in returns) / len(returns) * 252)
    peak = points[0]
    trough = peak
    in_drawdown = False
    longest = 0
    worst = 0.0
    recovery_days = None
    worst_in_episode = False
    for point in points[1:]:
        if point.nav >= peak.nav:
            if in_drawdown:
                longest = max(longest, (point.date - peak.date).days)
                if worst_in_episode:
                    recovery_days = (point.date - trough.date).days
            peak = trough = point
            in_drawdown = worst_in_episode = False
        else:
            in_drawdown = True
            if point.nav < trough.nav:
                trough = point
            drawdown = point.nav / peak.nav - 1
            if drawdown < worst:
                worst = drawdown
                worst_in_episode = True
                recovery_days = None
    if in_drawdown:
        longest = max(longest, (points[-1].date - peak.date).days)
    elapsed_days = (points[-1].date - points[0].date).days
    cagr = (points[-1].nav / points[0].nav) ** (365.2425 / elapsed_days) - 1
    metrics.update({
        "downside_volatility_pct": round(downside * 100, 4),
        "calmar_ratio": round(cagr / abs(worst), 4) if worst else None,
        "sortino_ratio": round(cagr / downside, 4) if downside else None,
        "max_drawdown_duration_days": longest,
        "recovery_days": recovery_days,
        "rolling_returns": {
            key: {k: v for k, v in value.items() if k != "windows"}
            for key, value in rolling_returns(points).items()
        },
    })
    return metrics
