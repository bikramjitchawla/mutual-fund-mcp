"""Index providers are deliberately separate from mutual-fund NAV providers."""

from __future__ import annotations

import csv
import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from clients.public_http import fetch_bytes
from models.schemas import NavPoint
from services.errors import FundError


@dataclass(frozen=True)
class Benchmark:
    benchmark_code: str
    name: str
    return_type: str = "total_return"
    source: str = "NSE Indices"


CATALOG = {
    "NIFTY_50_TRI": "NIFTY 50",
    "NIFTY_500_TRI": "NIFTY 500",
    "NIFTY_NEXT_50_TRI": "NIFTY NEXT 50",
    "NIFTY_MIDCAP_150_TRI": "NIFTY MIDCAP 150",
    "NIFTY_SMALLCAP_250_TRI": "NIFTY SMALLCAP 250",
}


class BenchmarkProvider(ABC):
    @abstractmethod
    def search_benchmarks(self, query: str) -> list[Benchmark]: ...

    @abstractmethod
    def get_history(
        self, benchmark_code: str, from_date: date, to_date: date
    ) -> tuple[Benchmark, list[NavPoint]]: ...


def benchmark_for(code: str) -> Benchmark:
    if code not in CATALOG:
        raise FundError(
            "BENCHMARK_NOT_FOUND",
            "Use search_benchmarks to select a supported benchmark code.",
        )
    return Benchmark(code, CATALOG[code] + " TRI")


class NSEBenchmarkProvider(BenchmarkProvider):
    def __init__(self, fetcher=fetch_bytes):
        self.fetcher = fetcher

    def search_benchmarks(self, query: str) -> list[Benchmark]:
        query = query.strip().casefold().replace("_", " ")
        return [
            benchmark_for(code)
            for code, name in CATALOG.items()
            if query in (code.replace("_", " ") + " " + name).casefold()
        ]

    def get_history(
        self, benchmark_code: str, from_date: date, to_date: date
    ) -> tuple[Benchmark, list[NavPoint]]:
        benchmark = benchmark_for(benchmark_code)
        name = CATALOG[benchmark_code]
        unique = {}
        start = from_date
        while start <= to_date:
            end = min(
                start + timedelta(days=min(364, (date.max - start).days)), to_date
            )
            info = {
                "name": name,
                "startDate": start.strftime("%d-%b-%Y"),
                "endDate": end.strftime("%d-%b-%Y"),
                "indexName": name,
            }
            payload = self.fetcher(
                "https://www.niftyindices.com/Backpage/getTotalReturnIndexString",
                payload={"cinfo": json.dumps(info)},
            )
            try:
                records = json.loads(payload)["d"]
                if isinstance(records, str):
                    records = json.loads(records)
                if not isinstance(records, list):
                    raise ValueError
                for row in records:
                    day = datetime.strptime(row["Date"], "%d %b %Y").date()
                    value = float(str(row["TotalReturnsIndex"]).replace(",", ""))
                    if not math.isfinite(value) or value <= 0:
                        raise ValueError
                    if start <= day <= end:
                        if day in unique and unique[day].nav != value:
                            raise ValueError
                        unique[day] = NavPoint(day, value)
            except (ValueError, TypeError, KeyError) as error:
                raise FundError(
                    "INVALID_PROVIDER_RESPONSE",
                    "NSE returned invalid total-return index data.",
                ) from error
            if end == to_date:
                break
            start = end + timedelta(days=1)
        if not unique:
            raise FundError(
                "NO_BENCHMARK_DATA",
                "No total-return index observations in the requested range.",
            )
        return benchmark, sorted(unique.values(), key=lambda point: point.date)


class CSVBenchmarkProvider(NSEBenchmarkProvider):
    """Operator-configured, validated CSV history when live NSE is unavailable.

    Files are selected only from a fixed benchmark catalog, never client paths.
    Columns: date,value. Dates: YYYY-MM-DD. Metadata: source recorded by operator.
    """

    def __init__(self, directory: str):
        self.directory = Path(directory).expanduser()

    def search_benchmarks(self, query: str) -> list[Benchmark]:
        return [
            b
            for b in super().search_benchmarks(query)
            if (self.directory / f"{b.benchmark_code}.csv").is_file()
        ]

    def get_history(
        self, benchmark_code: str, from_date: date, to_date: date
    ) -> tuple[Benchmark, list[NavPoint]]:
        benchmark = benchmark_for(benchmark_code)
        path = self.directory / f"{benchmark_code}.csv"
        try:
            if path.stat().st_size > 20 * 1024 * 1024:
                raise ValueError
            with path.open(newline="", encoding="utf-8-sig") as file:
                points = [
                    NavPoint(date.fromisoformat(row["date"]), float(row["value"]))
                    for row in csv.DictReader(file)
                ]
        except FileNotFoundError as error:
            raise FundError(
                "NO_BENCHMARK_DATA", "No imported CSV for this benchmark."
            ) from error
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise FundError(
                "INVALID_PROVIDER_RESPONSE",
                "Benchmark CSV must contain valid date,value columns.",
            ) from error
        from services.advanced_analytics import normalize_nav_points

        points = normalize_nav_points(points)
        selected = [p for p in points if from_date <= p.date <= to_date]
        if not selected:
            raise FundError(
                "NO_BENCHMARK_DATA", "CSV has no observations in the requested range."
            )
        return Benchmark(
            benchmark_code, benchmark.name, source="Operator-imported TRI CSV"
        ), selected
