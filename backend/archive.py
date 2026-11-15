"""Local columnar OHLCV archive.

Polars deduplicates and writes compressed Parquet. DuckDB scans the same files
directly for research queries without running a database server. This archive
contains provider-supplied bars only and is never used to manufacture quotes.
"""
from __future__ import annotations

import os
import logging
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

import duckdb
import polars as pl
from fastapi import HTTPException

from .assets import get_instrument

LOGGER = logging.getLogger(__name__)
ARCHIVE_LOCK = RLock()
BAR_SCHEMA = {
    "time": pl.Int64,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
}
ALLOWED_RANGES = {"1D", "1W", "1M", "3M", "6M", "1Y", "2Y", "5Y", "10Y", "MAX"}


def archive_path(asset_id: str, window: str) -> Path:
    get_instrument(asset_id)
    if window not in ALLOWED_RANGES:
        raise HTTPException(400, detail="Unsupported archive range.")
    root = Path(os.environ.get(
        "TRADING_SIM_MARKET_DIR",
        str(Path(__file__).resolve().parent.parent / "data" / "market"),
    ))
    return root / asset_id / (window + ".parquet")


def record_history(data: dict[str, Any]) -> None:
    """Persist a validated provider response; duplicate timestamps keep latest bar.

    Use atomic rename so interruption cannot leave a partially written .parquet.
    No file write is necessary if the provider returns no bars.
    """
    bars = data.get("bars") or []
    if not bars or data.get("is_demo", False):
        return
    path = archive_path(data["asset_id"], data["range"])
    columns = {column: [bar[column] for bar in bars] for column in BAR_SCHEMA}
    incoming = pl.DataFrame(columns, schema=BAR_SCHEMA)

    # Validate only sensible OHLCV values, then normalize order.
    incoming = incoming.filter(
        (pl.col("time") > 0)
        & (pl.col("open") > 0)
        & (pl.col("high") >= pl.max_horizontal(["open", "close", "low"]))
        & (pl.col("low") <= pl.min_horizontal(["open", "close", "high"]))
        & (pl.col("close") > 0)
        & (pl.col("volume") >= 0)
        & pl.all_horizontal([pl.col(field).is_finite() for field in ("open", "high", "low", "close", "volume")])
    )
    if incoming.is_empty():
        return

    with ARCHIVE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = pl.read_parquet(path).select(list(BAR_SCHEMA))
            incoming = pl.concat([existing, incoming], how="vertical")
        combined = incoming.unique(subset=["time"], keep="last").sort("time")
        temporary = path.parent / f".{path.name}.{uuid4().hex}.tmp"
        try:
            combined.write_parquet(temporary, compression="zstd")
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()


def archive_stats(asset_id: str, window: str) -> dict[str, Any]:
    path = archive_path(asset_id, window)
    if not path.exists():
        raise HTTPException(404, detail="No local archive for this instrument/timeframe. Load its chart first.")
    with ARCHIVE_LOCK:
        # Opening a new in-memory connection per request avoids shared-cursor races.
        with duckdb.connect(":memory:") as con:
            row = con.execute(
                """SELECT count(*) AS bars,
                          min(time) AS first_timestamp,
                          max(time) AS last_timestamp,
                          min(low) AS lowest_price,
                          max(high) AS highest_price,
                          avg(volume) AS avg_volume
                   FROM read_parquet(?)""",
                [str(path)],
            ).fetchone()
    return {
        "asset_id": asset_id, "range": window,
        "bars": int(row[0]), "first_timestamp": row[1],
        "last_timestamp": row[2], "lowest_price": row[3],
        "highest_price": row[4], "average_volume": row[5],
        "storage": "local zstd parquet", "price_source": "archived provider candles (not an executable quote)",
    }


def load_archived_history(asset_id: str, window: str) -> list[dict[str, int | float]]:
    """Return recorded provider bars when the external feed is unavailable.

    Archive is an offline *historical snapshot*, never a current exchange quote.
    """
    path = archive_path(asset_id, window)
    if not path.exists():
        return []
    with ARCHIVE_LOCK:
        rows = pl.read_parquet(path).sort("time").tail(1000).to_dicts()
    return [{column: row[column] for column in BAR_SCHEMA} for row in rows]
