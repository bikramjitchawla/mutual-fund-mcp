"""Deterministic overlap of validated, same-date, ISIN-keyed portfolios."""

from __future__ import annotations

import math
from itertools import combinations

from services.errors import FundError

OVERLAP_LEVELS = (
    (50, "High", "🔴", "These portfolios have substantial duplication."),
    (
        25,
        "Moderate",
        "🟡",
        "These portfolios share a meaningful core while retaining distinct holdings.",
    ),
    (
        0,
        "Low",
        "🟢",
        "These portfolios have limited duplication within the imported holdings.",
    ),
)


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
        unique_holdings = []
        for code, other in ((left, right), (right, left)):
            unique = [
                security_row(isin, [code])
                for isin in portfolios[code].keys() - portfolios[other].keys()
            ]
            unique.sort(
                key=lambda row: (
                    -row["funds"][0]["portfolio_weight_pct"],
                    row["security_name"].casefold(),
                    row["isin"],
                )
            )
            unique_holdings.append(
                {
                    "scheme_code": code,
                    "scheme_name": names[code],
                    "unique_security_count": len(unique),
                    "securities": unique,
                }
            )
        pairwise.append(
            {
                "scheme_codes": [left, right],
                "shared_security_count": len(holdings),
                "weighted_overlap_pct": round(
                    math.fsum(h["overlap_contribution_pct"] for h in holdings), 6
                ),
                "shared_securities": holdings,
                "unique_holdings": unique_holdings,
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


def compact_overlap(
    result: dict, max_common_items: int = 10, max_unique_items: int = 4
) -> dict:
    """Create a concise, presentation-ready view of a full overlap result."""
    validate_overlap_limit(max_common_items, "max_common_items")
    validate_overlap_limit(max_unique_items, "max_unique_items")
    fund_names = {
        fund["scheme_code"]: _short_fund_name(fund["scheme_name"])
        for fund in result["funds"]
    }
    comparisons = []
    text_blocks = []
    for pair in result["pairwise"]:
        left, right = pair["scheme_codes"]
        overlap = round(pair["weighted_overlap_pct"], 2)
        level, indicator, interpretation = _overlap_level(overlap)
        top_common = [
            {
                "isin": security["isin"],
                "security_name": _short_security_name(security["security_name"]),
                "overlap_weight_pct": round(security["overlap_contribution_pct"], 2),
                "fund_weights": [
                    {
                        "scheme_code": fund["scheme_code"],
                        "portfolio_weight_pct": round(fund["portfolio_weight_pct"], 2),
                    }
                    for fund in security["funds"]
                ],
            }
            for security in pair["shared_securities"][:max_common_items]
        ]
        unique_by_fund = []
        for unique in pair["unique_holdings"]:
            top_unique = [
                {
                    "isin": security["isin"],
                    "security_name": _short_security_name(security["security_name"]),
                    "portfolio_weight_pct": round(
                        security["funds"][0]["portfolio_weight_pct"], 2
                    ),
                }
                for security in unique["securities"][:max_unique_items]
            ]
            unique_by_fund.append(
                {
                    "scheme_code": unique["scheme_code"],
                    "scheme_name": fund_names[unique["scheme_code"]],
                    "unique_security_count": unique["unique_security_count"],
                    "top_unique_holdings": top_unique,
                }
            )
        difference_notes = _difference_notes(unique_by_fund)
        comparison = {
            "title": f"{fund_names[left]} vs {fund_names[right]}",
            "scheme_codes": [left, right],
            "portfolio_overlap_pct": overlap,
            "overlap_level": level,
            "indicator": indicator,
            "common_security_count": pair["shared_security_count"],
            "top_common_holdings": top_common,
            "unique_holdings": unique_by_fund,
            "interpretation": " ".join([interpretation, *difference_notes]),
        }
        comparisons.append(comparison)
        text_blocks.append(_summary_text(comparison))
    return {
        "comparisons": comparisons,
        "summary_text": "\n\n".join(text_blocks),
        "items_shown": {
            "common": max_common_items,
            "unique_per_fund": max_unique_items,
        },
    }


def validate_overlap_limit(value: int, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 25:
        raise FundError("INVALID_LIMIT", f"{name} must be an integer from 1 to 25.")


def _difference_notes(unique_by_fund: list[dict]) -> list[str]:
    notes = []
    for fund in unique_by_fund:
        holdings = fund["top_unique_holdings"]
        if len(holdings) >= 2 and all(
            not holding["isin"].startswith("IN") for holding in holdings
        ):
            notes.append(
                f"{fund['scheme_name']}'s {len(holdings)} largest unique holdings "
                "are international securities."
            )
    return notes


def _overlap_level(overlap: float) -> tuple[str, str, str]:
    for minimum, level, indicator, interpretation in OVERLAP_LEVELS:
        if overlap >= minimum:
            return level, indicator, interpretation
    raise AssertionError("overlap classification is exhaustive")


def _short_fund_name(name: str) -> str:
    for suffix in (" - Direct Plan - Growth", " - Direct Growth"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return name.removesuffix(" Fund")


def _short_security_name(name: str) -> str:
    for suffix in (" Limited", " Ltd.", " Ltd"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def _summary_text(comparison: dict) -> str:
    lines = [
        comparison["title"],
        (
            f"Portfolio overlap: {comparison['portfolio_overlap_pct']:.2f}%  "
            f"{comparison['indicator']} {comparison['overlap_level']}"
        ),
        f"{comparison['common_security_count']} common securities",
        "",
        "Top common holdings",
    ]
    if comparison["top_common_holdings"]:
        lines.extend(
            f"{holding['security_name']}: {holding['overlap_weight_pct']:.2f}%"
            for holding in comparison["top_common_holdings"]
        )
    else:
        lines.append("None")
    lines.extend(["", "Key differences"])
    for fund in comparison["unique_holdings"]:
        lines.append(f"{fund['scheme_name']} uniquely holds:")
        if fund["top_unique_holdings"]:
            lines.extend(
                f"{holding['security_name']}: {holding['portfolio_weight_pct']:.2f}%"
                for holding in fund["top_unique_holdings"]
            )
        else:
            lines.append("None")
        lines.append("")
    lines.append(f"Interpretation: {comparison['interpretation']}")
    return "\n".join(lines)
