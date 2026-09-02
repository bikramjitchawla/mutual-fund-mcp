from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

from models.schemas import FundScheme, NavPoint


class MutualFundProvider(ABC):
    """Provider-independent interface used by the service layer."""

    source = "Unknown"

    @abstractmethod
    def search_funds(self, query: str) -> list[FundScheme]:
        raise NotImplementedError

    @abstractmethod
    def get_latest_nav(self, scheme_code: str) -> tuple[FundScheme, NavPoint]:
        raise NotImplementedError

    @abstractmethod
    def get_nav_history(
        self, scheme_code: str, from_date: date, to_date: date
    ) -> tuple[FundScheme, list[NavPoint]]:
        raise NotImplementedError

