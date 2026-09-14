"""Bounded HTTP retrieval for the public index and disclosure adapters."""

import time

import httpx

from services.errors import FundError

MAX_BYTES = 20 * 1024 * 1024


def fetch_bytes(url: str, *, payload: dict | None = None) -> bytes:
    with httpx.Client(
        timeout=15,
        follow_redirects=False,
        headers={
            "User-Agent": "mutual-fund-mcp/0.1 (public financial data research)",
            "Referer": "https://www.niftyindices.com/reports/historical-data",
        },
    ) as client:
        for attempt in range(2):
            try:
                with client.stream(
                    "POST" if payload is not None else "GET", url, json=payload
                ) as response:
                    response.raise_for_status()
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_BYTES:
                            raise FundError(
                                "INVALID_PROVIDER_RESPONSE",
                                "Public data response exceeded 20 MiB.",
                            )
                    return bytes(content)
            except httpx.HTTPError as error:
                if attempt == 1:
                    raise FundError(
                        "PROVIDER_UNAVAILABLE",
                        "Public data provider could not be reached; retry later.",
                    ) from error
                time.sleep(0.5)
    raise AssertionError("unreachable")
