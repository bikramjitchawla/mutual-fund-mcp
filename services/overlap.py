"""Deterministic overlap of validated, same-date, ISIN-keyed portfolios."""

from __future__ import annotations

import math
from itertools import combinations

from services.errors import FundError


def calculate_overlap(snapshots: list[dict]) -> dict:
    """Compare long cash-security positions without renormalizing reported weights."""
    codes = [snapshot["scheme_code"] for snapshot in snapshots]
    if len(codes) < 2 or len(set(codes)) != len(codes):
        raise FundError(
            "INVALID_COMPARISON", "Overlap requires distinct fund snapshots."
        )
    if len({snapshot["portfolio_date"] for snapshot in snapshots}) != 1:
        raise FundError(
            "INVALID_COMPARISON", "Overlap snapshots must share a portfolio date."
        )
    portfolios = {
        snapshot["scheme_code"]: {
            holding["isin"]: holding
            for holding in snapshot["holdings"]
            if holding["quantity"] > 0
        }
        for snapshot in snapshots
    }
    names = {s["scheme_code"]: s["scheme_name"] for s in snapshots}
    memberships = {}
    for code, holdings in portfolios.items():
        for isin in holdings:
            memberships.setdefault(isin, []).append(code)

    def security_row(isin: str, owners: list[str]) -> dict:
        first = portfolios[owners[0]][isin]
        return {
            "isin": isin,
            "security_name": first["security_name"],
            "fund_count": len(owners),
            "funds": [
                {
                    "scheme_code": code,
                    "scheme_name": names[code],
                    "security_name": portfolios[code][isin]["security_name"],
                    "portfolio_weight_pct": portfolios[code][isin][
                        "portfolio_weight_pct"
                    ],
                }
                for code in owners
            ],
        }

    shared = [
        security_row(isin, owners)
        for isin, owners in memberships.items()
        if len(owners) >= 2
    ]
    shared.sort(
        key=lambda row: (
            -row["fund_count"],
            row["security_name"].casefold(),
            row["isin"],
        )
    )
    common = set.intersection(*(set(p) for p in portfolios.values()))
    pairwise = []
    for left, right in combinations(codes, 2):
        common_pair = portfolios[left].keys() & portfolios[right].keys()
        holdings = []
        for isin in common_pair:
            row = security_row(isin, [left, right])
            row["overlap_contribution_pct"] = min(
                f["portfolio_weight_pct"] for f in row["funds"]
            )
            holdings.append(row)
        holdings.sort(key=lambda row: (-row["overlap_contribution_pct"], row["isin"]))
        pairwise.append(
            {
                "scheme_codes": [left, right],
                "shared_security_count": len(holdings),
                "weighted_overlap_pct": round(
                    math.fsum(h["overlap_contribution_pct"] for h in holdings), 6
                ),
                "shared_securities": holdings,
            }
        )

    funds = []
    for snapshot in snapshots:
        code = snapshot["scheme_code"]
        holdings = portfolios[code]
        unique = [
            security_row(isin, [code])
            for isin in holdings
            if len(memberships[isin]) == 1
        ]
        unique.sort(key=lambda row: (row["security_name"].casefold(), row["isin"]))
        funds.append(
            {
                "scheme_code": code,
                "scheme_name": snapshot["scheme_name"],
                "security_count": len(holdings),
                "reported_weight_sum_pct": round(
                    math.fsum(h["portfolio_weight_pct"] for h in holdings.values()), 6
                ),
                "unique_security_count": len(unique),
                "unique_securities": unique,
                "source": snapshot["source"],
                "retrieved_at": snapshot["retrieved_at"],
                "portfolio_date": snapshot["portfolio_date"],
            }
        )
    return {
        "funds": funds,
        "shared_security_count": len(shared),
        "shared_securities": shared,
        "common_to_all_security_count": len(common),
        "common_to_all_isins": sorted(common),
        "common_to_all_weighted_overlap_pct": round(
            math.fsum(
                min(p[isin]["portfolio_weight_pct"] for p in portfolios.values())
                for isin in common
            ),
            6,
        ),
        "pairwise": pairwise,
        "method": {
            "matching": "Exact ISIN, with positive quantities; a positive position with a published zero weight is still shared.",
            "shared_securities": "Held by at least two selected funds; common_to_all refers to every selected fund.",
            "unique_securities": "Held by only one of the selected funds, not necessarily unique in the market.",
            "weighted_overlap": "Sum of min(weight_A, weight_B) for each shared ISIN. Weights use percentage points of each full portfolio and are not renormalized.",
            "common_to_all_weighted_overlap": "Sum of the smallest weight across all selected funds for each ISIN held by all of them; not an average of pairwise overlaps.",
            "scope": "All imported ISIN cash securities, including stocks, bonds, REITs and fund units; not an equity-only or net derivative exposure measure. Excluded assets can prevent identical imported portfolios from reporting 100% overlap.",
        },
    }
