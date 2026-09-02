from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Callable
from urllib.parse import urlencode

import httpx

from clients.base import MutualFundProvider
from models.schemas import FundScheme, NavPoint
from services.errors import FundError

LATEST_NAV_URL = "https://www.amfiindia.com/spages/NAVAll.txt"
HISTORY_URL = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx"
USER_AGENT = "mutual-fund-mcp/0.1 (+read-only AMFI client)"
SCHEME_CODE_RE = re.compile(r"^[0-9]{1,12}$")
MAX_RESPONSE_BYTES = 100 * 1024 * 1024


class AMFIProvider(MutualFundProvider):
    source = "AMFI"

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        max_retries: int = 3,
        history_chunk_days: int = 90,
        fetcher: Callable[[str], str] | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max_retries
        self.history_chunk_days = history_chunk_days
        self._fetcher = fetcher

    def search_funds(self, query: str) -> list[FundScheme]:
        cleaned = " ".join(query.split()).casefold()
        if len(cleaned) < 2:
            raise FundError("INVALID_QUERY", "Search query must contain at least two characters.")
        schemes = self._parse_latest(self._get(LATEST_NAV_URL))
        tokens = cleaned.split()
        matches = [
            scheme
            for scheme, _ in schemes.values()
            if all(token in scheme.scheme_name.casefold() for token in tokens)
        ]
        matches.sort(
            key=lambda scheme: (
                0 if cleaned in scheme.scheme_name.casefold() else 1,
                len(scheme.scheme_name),
                scheme.scheme_name,
            )
        )
        return matches[:20]

    def get_latest_nav(self, scheme_code: str) -> tuple[FundScheme, NavPoint]:
        self._validate_scheme_code(scheme_code)
        record = self._parse_latest(self._get(LATEST_NAV_URL)).get(scheme_code)
        if record is None:
            raise FundError("SCHEME_NOT_FOUND", "No scheme matched the supplied scheme code.")
        return record

    def get_nav_history(
        self, scheme_code: str, from_date: date, to_date: date
    ) -> tuple[FundScheme, list[NavPoint]]:
        self._validate_scheme_code(scheme_code)
        records: dict[date, NavPoint] = {}
        scheme: FundScheme | None = None

        chunk_start = from_date
        while chunk_start <= to_date:
            chunk_end = min(chunk_start + timedelta(days=self.history_chunk_days - 1), to_date)
            query = urlencode(
                {
                    "tp": "1",
                    "frmdt": chunk_start.strftime("%d-%b-%Y"),
                    "todt": chunk_end.strftime("%d-%b-%Y"),
                }
            )
            parsed_scheme, points = self._parse_history(
                self._get(f"{HISTORY_URL}?{query}"), scheme_code
            )
            if parsed_scheme is not None:
                scheme = parsed_scheme
            for point in points:
                if from_date <= point.date <= to_date:
                    records[point.date] = point
            chunk_start = chunk_end + timedelta(days=1)

        if scheme is None:
            # Distinguish an invalid code from a valid scheme with no observations in the range.
            latest = self._parse_latest(self._get(LATEST_NAV_URL)).get(scheme_code)
            if latest is None:
                raise FundError("SCHEME_NOT_FOUND", "No scheme matched the supplied scheme code.")
            scheme = latest[0]
        if not records:
            raise FundError("NO_NAV_DATA", "No NAV observations are available in the requested period.")
        return scheme, sorted(records.values(), key=lambda point: point.date)

    def _get(self, url: str) -> str:
        if self._fetcher is not None:
            return self._fetcher(url)
        last_error: Exception | None = None
        with httpx.Client(
            timeout=self.timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "text/plain"},
            follow_redirects=True,
            verify=True,
        ) as client:
            for attempt in range(self.max_retries):
                try:
                    response = client.get(url)
                    if response.status_code == 429:
                        raise FundError("RATE_LIMITED", "AMFI rate limited the request.")
                    response.raise_for_status()
                    try:
                        content_length = int(response.headers.get("Content-Length", "0"))
                    except ValueError as error:
                        raise FundError(
                            "INVALID_PROVIDER_RESPONSE", "AMFI returned an invalid Content-Length."
                        ) from error
                    if content_length > MAX_RESPONSE_BYTES or len(response.content) > MAX_RESPONSE_BYTES:
                        raise FundError(
                            "INVALID_PROVIDER_RESPONSE", "AMFI response exceeded the size limit."
                        )
                    text = response.text.lstrip("\ufeff")
                    if "<html" in text[:500].casefold():
                        raise FundError(
                            "INVALID_PROVIDER_RESPONSE", "AMFI returned HTML instead of NAV data."
                        )
                    return text
                except FundError as error:
                    last_error = error
                    if error.code == "RATE_LIMITED":
                        retry_after = response.headers.get("Retry-After")
                        delay = self._retry_after_seconds(retry_after, attempt)
                    else:
                        delay = 2**attempt
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as error:
                    last_error = error
                    delay = 2**attempt
                if attempt + 1 < self.max_retries:
                    time.sleep(delay)
        if isinstance(last_error, FundError):
            raise last_error
        raise FundError("PROVIDER_UNAVAILABLE", "AMFI could not be reached after bounded retries.")

    @staticmethod
    def _retry_after_seconds(value: str | None, attempt: int) -> float:
        if value:
            try:
                return min(float(value), 30.0)
            except ValueError:
                try:
                    return max(0.0, min((parsedate_to_datetime(value) - datetime.now().astimezone()).total_seconds(), 30.0))
                except (TypeError, ValueError):
                    pass
        return float(2**attempt)

    @staticmethod
    def _validate_scheme_code(scheme_code: str) -> None:
        if not SCHEME_CODE_RE.fullmatch(scheme_code):
            raise FundError("SCHEME_NOT_FOUND", "Scheme code must contain only digits.")

    @staticmethod
    def _parse_date(value: str) -> date:
        try:
            return datetime.strptime(value.strip(), "%d-%b-%Y").date()
        except ValueError as error:
            raise FundError("INVALID_PROVIDER_RESPONSE", "AMFI returned an invalid NAV date.") from error

    @classmethod
    def _parse_latest(cls, payload: str) -> dict[str, tuple[FundScheme, NavPoint]]:
        results: dict[str, tuple[FundScheme, NavPoint]] = {}
        fund_house = "Unknown"
        for raw_line in payload.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            fields = [field.strip() for field in line.split(";")]
            if len(fields) == 6 and fields[0].isdigit():
                try:
                    nav = float(fields[4])
                    nav_date = cls._parse_date(fields[5])
                except ValueError as error:
                    raise FundError("INVALID_PROVIDER_RESPONSE", "AMFI returned a non-numeric NAV.") from error
                if nav <= 0:
                    raise FundError("INVALID_PROVIDER_RESPONSE", "AMFI returned a non-positive NAV.")
                scheme = FundScheme(fields[0], fields[3], fund_house, fields[1] or None, fields[2] or None)
                results[fields[0]] = (scheme, NavPoint(nav_date, nav))
            elif ";" not in line and not line.casefold().startswith(("open ended", "close ended", "interval fund")):
                fund_house = line
        if not results:
            raise FundError("INVALID_PROVIDER_RESPONSE", "AMFI returned no valid latest NAV records.")
        return results

    @classmethod
    def _parse_history(
        cls, payload: str, scheme_code: str
    ) -> tuple[FundScheme | None, list[NavPoint]]:
        fund_house = "Unknown"
        scheme: FundScheme | None = None
        points: list[NavPoint] = []
        for raw_line in payload.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            fields = [field.strip() for field in line.split(";")]
            if len(fields) >= 8 and fields[0] == scheme_code:
                try:
                    nav = float(fields[4])
                    nav_date = cls._parse_date(fields[7])
                except ValueError as error:
                    raise FundError("INVALID_PROVIDER_RESPONSE", "AMFI returned a non-numeric NAV.") from error
                if nav <= 0:
                    raise FundError("INVALID_PROVIDER_RESPONSE", "AMFI returned a non-positive NAV.")
                scheme = FundScheme(fields[0], fields[1], fund_house, fields[2] or None, fields[3] or None)
                points.append(NavPoint(nav_date, nav))
            elif ";" not in line and not line.casefold().startswith(("open ended", "close ended", "interval fund")):
                fund_house = line
        return scheme, points
