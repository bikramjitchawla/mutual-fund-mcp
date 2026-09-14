"""Atomic, persistent monthly holdings snapshots for local MCP deployments."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from services.mutual_funds import MutualFundService


class HoldingsStore:
    def __init__(self, path: str):
        self.path = Path(path).expanduser()

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=15)
        try:
            db.execute("PRAGMA foreign_keys = ON")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                    scheme_code TEXT NOT NULL, portfolio_date TEXT NOT NULL,
                    scheme_name TEXT NOT NULL, source TEXT NOT NULL,
                    retrieved_at TEXT NOT NULL, scope TEXT NOT NULL,
                    PRIMARY KEY(scheme_code, portfolio_date)
                );
                CREATE TABLE IF NOT EXISTS portfolio_holdings (
                    scheme_code TEXT NOT NULL, portfolio_date TEXT NOT NULL,
                    isin TEXT NOT NULL, security_name TEXT NOT NULL, sector TEXT,
                    quantity REAL NOT NULL, market_value REAL NOT NULL,
                    portfolio_weight_pct REAL NOT NULL,
                    PRIMARY KEY(scheme_code, portfolio_date, isin),
                    FOREIGN KEY(scheme_code, portfolio_date) REFERENCES
                    portfolio_snapshots(scheme_code, portfolio_date) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS holdings_isin ON portfolio_holdings(isin, portfolio_date);
            """)
            db.row_factory = sqlite3.Row
            yield db
        finally:
            db.close()

    def save(self, snapshot: dict) -> None:
        # A transaction preserves the previous snapshot on any insertion failure.
        with self.connect() as db, db:
            key = (snapshot["scheme_code"], snapshot["portfolio_date"])
            db.execute(
                "DELETE FROM portfolio_snapshots WHERE scheme_code=? AND portfolio_date=?",
                key,
            )
            db.execute(
                "INSERT INTO portfolio_snapshots VALUES (?,?,?,?,?,?)",
                (
                    *key,
                    snapshot["scheme_name"],
                    snapshot["source"],
                    MutualFundService._now(),
                    snapshot["scope"],
                ),
            )
            db.executemany(
                "INSERT INTO portfolio_holdings VALUES (?,?,?,?,?,?,?,?)",
                [
                    (
                        *key,
                        h["isin"],
                        h["security_name"],
                        h["sector"],
                        h["quantity"],
                        h["market_value"],
                        h["portfolio_weight_pct"],
                    )
                    for h in snapshot["holdings"]
                ],
            )

    def get(self, scheme_code: str, portfolio_date: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM portfolio_snapshots WHERE scheme_code=? AND portfolio_date=?",
                (scheme_code, portfolio_date),
            ).fetchone()
            if row is None:
                return None
            snapshot = dict(row)
            snapshot["holdings"] = [
                dict(h)
                for h in db.execute(
                    "SELECT isin,security_name,sector,quantity,market_value,portfolio_weight_pct FROM portfolio_holdings WHERE scheme_code=? AND portfolio_date=? ORDER BY portfolio_weight_pct DESC,isin",
                    (scheme_code, portfolio_date),
                )
            ]
            return snapshot
