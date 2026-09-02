from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class FundScheme:
    scheme_code: str
    scheme_name: str
    fund_house: str | None
    isin_growth: str | None = None
    isin_reinvestment: str | None = None


@dataclass(frozen=True, slots=True)
class NavPoint:
    date: date
    nav: float
