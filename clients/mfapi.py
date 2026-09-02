from __future__ import annotations

import json
import re
import time
from datetime import date, datetime
from typing import Any, Callable
from urllib.parse import quote, urlencode

import httpx

from clients.base import MutualFundProvider
from models.schemas import FundScheme, NavPoint
from services.errors import FundError

BASE_URL = "https://api.mfapi.in"
USER_AGENT = "mutual-fund-mcp/0.1 (+read-only MFAPI client)"
SCHEME_CODE_RE = re.compile(r"^[0-9]{1,12}$")
MAX_RESPONSE_BYTES = 20 * 1024 * 1024


class MFAPIProvider(MutualFundProvider):
    """Fast JSON provider suited to interactive, scheme-specific history queries."""

    source = "MFAPI.in"

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        max_retries: int = 3,
        fetcher: Callable[[str], Any] | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self._fetcher = fetcher

    def search_funds(self, query: str) -> list[FundScheme]:
        cleaned = " ".join(query.split())
        if len(cleaned) < 2:
            raise FundError("INVALID_QUERY", "Search query must contain at least two characters.")
        payload = self._get_json(f"{BASE_URL}/mf/search?{urlencode({'q': cleaned})}")
        if not isinstance(payload, list):
            raise FundError("INVALID_PROVIDER_RESPONSE", "MFAPI.in returned an invalid search response.")
        results = []
        for record in payload[:20]:
            if not isinstance(record, dict):
                continue
            code = record.get("schemeCode")
            name = record.get("schemeName")
            if code is None or not isinstance(name, str) or not name.strip():
                continue
            results.append(
                FundScheme(
                    str(code),
                    name.strip(),
                    record.get("fundHouse") or record.get("fund_house"),
                    record.get("isinGrowth"),
                    record.get("isinDivReinvestment"),
                )
            )
        return results

    def get_latest_nav(self, scheme_code: str) -> tuple[FundScheme, NavPoint]:
        self._validate_scheme_code(scheme_code)
        payload = self._get_json(f"{BASE_URL}/mf/{quote(scheme_code, safe='')}/latest")
        scheme, points = self._parse_fund(payload, scheme_code)
        if not points:
            raise FundError("NO_NAV_DATA", "No latest NAV is available for this scheme.")
        return scheme, max(points, key=lambda point: point.date)

    def get_nav_history(
        self, scheme_code: str, from_date: date, to_date: date
    ) -> tuple[FundScheme, list[NavPoint]]:
        self._validate_scheme_code(scheme_code)
        query = urlencode({"startDate": from_date.isoformat(), "endDate": to_date.isoformat()})
        payload = self._get_json(f"{BASE_URL}/mf/{quote(scheme_code, safe='')}?{query}")
        scheme, points = self._parse_fund(payload, scheme_code)
        # Filter locally too: this guarantees the contract if a provider ignores query parameters.
        unique = {point.date: point for point in points if from_date <= point.date <= to_date}
        filtered = sorted(unique.values(), key=lambda point: point.date)
        if not filtered:
            raise FundError("NO_NAV_DATA", "No NAV observations are available in the requested period.")
        return scheme, filtered

    def _get_json(self, url: str) -> Any:
        if self._fetcher is not None:
            payload = self._fetcher(url)
            if isinstance(payload, str):
                try:
                    return json.loads(payload)
                except json.JSONDecodeError as error:
                    raise FundError("INVALID_PROVIDER_RESPONSE", "MFAPI.in returned invalid JSON.") from error
            return payload

        last_error: Exception | None = None
        with httpx.Client(
            timeout=self.timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
            verify=True,
        ) as client:
            for attempt in range(self.max_retries):
                try:
                    response = client.get(url)
                    if response.status_code == 404:
                        raise FundError("SCHEME_NOT_FOUND", "No scheme matched the supplied scheme code.")
                    if response.status_code == 429:
                        last_error = FundError("RATE_LIMITED", "MFAPI.in rate limited the request.")
                    else:
                        response.raise_for_status()
                        content_length = int(response.headers.get("Content-Length", "0"))
                        if content_length > MAX_RESPONSE_BYTES or len(response.content) > MAX_RESPONSE_BYTES:
                            raise FundError("INVALID_PROVIDER_RESPONSE", "Provider response exceeded the size limit.")
                        try:
                            return response.json()
                        except json.JSONDecodeError as error:
                            raise FundError("INVALID_PROVIDER_RESPONSE", "MFAPI.in returned invalid JSON.") from error
                except FundError as error:
                    if error.code in {"SCHEME_NOT_FOUND", "INVALID_PROVIDER_RESPONSE"}:
                        raise
                    last_error = error
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError, ValueError) as error:
                    last_error = error
                if attempt + 1 < self.max_retries:
                    time.sleep(2**attempt)
        if isinstance(last_error, FundError):
            raise last_error
        raise FundError("PROVIDER_UNAVAILABLE", "MFAPI.in could not be reached after bounded retries.")

    @classmethod
    def _parse_fund(cls, payload: Any, requested_code: str) -> tuple[FundScheme, list[NavPoint]]:
        if not isinstance(payload, dict):
            raise FundError("INVALID_PROVIDER_RESPONSE", "MFAPI.in returned an invalid fund response.")
        if str(payload.get("status", "SUCCESS")).upper() != "SUCCESS":
            raise FundError("SCHEME_NOT_FOUND", "No scheme matched the supplied scheme code.")
        meta = payload.get("meta")
        data = payload.get("data")
        if not isinstance(meta, dict) or not isinstance(data, list):
            raise FundError("INVALID_PROVIDER_RESPONSE", "MFAPI.in omitted required fund fields.")
        code = str(meta.get("scheme_code", ""))
        name = meta.get("scheme_name")
        if code != requested_code or not isinstance(name, str) or not name.strip():
            raise FundError("INVALID_PROVIDER_RESPONSE", "MFAPI.in returned mismatched scheme metadata.")
        scheme = FundScheme(
            code,
            name.strip(),
            meta.get("fund_house"),
            meta.get("isin_growth"),
            meta.get("isin_div_reinvestment"),
        )
        points = []
        for record in data:
            if not isinstance(record, dict):
                raise FundError("INVALID_PROVIDER_RESPONSE", "MFAPI.in returned an invalid NAV record.")
            try:
                nav = float(record["nav"])
                nav_date = datetime.strptime(record["date"], "%d-%m-%Y").date()
            except (KeyError, TypeError, ValueError) as error:
                raise FundError("INVALID_PROVIDER_RESPONSE", "MFAPI.in returned an invalid NAV record.") from error
            if nav <= 0:
                raise FundError("INVALID_PROVIDER_RESPONSE", "MFAPI.in returned a non-positive NAV.")
            points.append(NavPoint(nav_date, nav))
        return scheme, points

    @staticmethod
    def _validate_scheme_code(scheme_code: str) -> None:
        if not SCHEME_CODE_RE.fullmatch(scheme_code):
            raise FundError("SCHEME_NOT_FOUND", "Scheme code must contain only digits.")

