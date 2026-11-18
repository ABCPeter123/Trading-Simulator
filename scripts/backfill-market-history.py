"""Owner-only local, rate-limited historical OHLCV backfill.

Provider data is never committed. CLI operates only in local research mode.
By default downloads 20 years (or as much as the provider has) of daily
history for a diversified public reference list. No private strategy input.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import market  # noqa: E402
from backend.assets import get_instrument, list_instruments  # noqa: E402
from fastapi import HTTPException  # noqa: E402

PRESETS = {
    "diversified": (
        "spy", "qqq", "iwm", "vti", "efa", "eem", "tlt", "ief", "shy",
        "tip", "sgov", "lqd", "hyg", "gld", "slv", "dbc", "vnq",
        "xiu", "vfv", "vdy", "xbal", "vab", "usdcad", "eurusd",
        "btcusd", "ethusd",
    ),
    "canada": (
        "vfv", "vdy", "xbal", "xgro", "xeqt", "xiu", "xqq", "zsp",
        "vab", "zag", "xre", "xeg", "zeb", "hdiv", "hyld",
        "ry", "td", "bmo", "bns", "cm", "cnr", "cp", "enb", "cnq",
        "shop", "usdcad",
    ),
    "global": (
        "spy", "qqq", "vxus", "vea", "vwo", "acwi", "ewj", "ewc",
        "ewg", "ewz", "fxi", "kweb", "eem", "efa", "vt", "vti",
        "dxy", "eurusd", "gbpusd", "usdcad", "btcusd", "ethusd",
        "solusd", "gld", "slv", "dbc",
    ),
}


def target_ids(preset: str | None, ids: str, limit: int) -> list[str]:
    choices = list(PRESETS[preset]) if preset else []
    choices.extend(entry.strip().lower() for entry in ids.split(",") if entry.strip())
    # Stable order, no repeated provider requests for the same instrument.
    choices = list(dict.fromkeys(choices))
    if not choices:
        raise ValueError("Choose --preset diversified|canada|global or --ids spy,qqq,...")
    if len(choices) > limit:
        raise ValueError(f"Requested {len(choices)} instruments, above --limit={limit}.")
    for symbol in choices:
        get_instrument(symbol)
    return choices


def backfill(ids: list[str], window: str, delay: float,
             fetch=market.history, pause=time.sleep, emit=print) -> dict:
    if window not in ("10Y", "15Y", "20Y", "MAX"):
        raise ValueError("Backfill supports 10Y, 15Y, 20Y or MAX daily data.")
    result = {"requested": len(ids), "downloaded": 0,
              "offline_only": 0, "unavailable": 0, "bars": 0}
    for index, asset_id in enumerate(ids):
        try:
            instrument = get_instrument(asset_id)
            if not instrument.ticker:
                raise ValueError("No actual provider ticker.")
            response = fetch(asset_id, window)
            bars = response["bars"]
            if not bars:
                raise ValueError("No observed OHLCV.")
            first = datetime.fromtimestamp(int(bars[0]["time"]), timezone.utc).date()
            last = datetime.fromtimestamp(int(bars[-1]["time"]), timezone.utc).date()
            if response.get("offline_cache"):
                result["offline_only"] += 1
                status = "OFFLINE ARCHIVE"
            else:
                result["downloaded"] += 1
                status = "ARCHIVED"
            result["bars"] += len(bars)
            emit(f"[{index+1}/{len(ids)}] {asset_id}: {status}, {len(bars)} observed "
                 f"daily bars, {first.isoformat()} to {last.isoformat()}")
        except (HTTPException, ValueError, KeyError, TypeError, OSError) as exc:
            result["unavailable"] += 1
            emit(f"[{index+1}/{len(ids)}] {asset_id}: unavailable ({type(exc).__name__}), no fabricated data.")
        if index < len(ids)-1 and delay > 0:
            pause(delay)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local-only historical market data backfill.")
    parser.add_argument("--preset", choices=tuple(PRESETS))
    parser.add_argument("--ids", default="", help="Comma-separated local catalog IDs")
    parser.add_argument("--window", choices=("10Y", "15Y", "20Y", "MAX"), default="20Y")
    parser.add_argument("--limit", type=int, default=50,
                        help="Maximum instruments per command, 1-500 (default 50)")
    parser.add_argument("--delay", type=float, default=0.75,
                        help="Delay between provider requests, seconds (default 0.75)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 500:
        parser.error("--limit must be between 1 and 500")
    if not 0.25 <= args.delay <= 30:
        parser.error("--delay must be 0.25 to 30 seconds")
    # Never download owner research data into a public demo's sandbox.
    import os
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO") == "1":
        parser.error("Private historical backfill is unavailable in public demo mode")
    try:
        ids = target_ids(args.preset, args.ids, args.limit)
    except (HTTPException, ValueError) as exc:
        parser.error("Invalid or unknown instrument IDs, or too many requests.")
    if args.dry_run:
        print(f"Dry run: {len(ids)} known catalog IDs, {args.window} daily window.")
        print(", ".join(ids))
        return 0
    print(f"Downloading up to {args.window} of real daily OHLCV for {len(ids)} instruments "
          "to Git-ignored local Parquet. Actual available history varies by provider.")
    summary = backfill(ids, args.window, args.delay)
    print(f"Done: {summary['downloaded']} newly fetched, "
          f"{summary['offline_only']} existing offline snapshots, "
          f"{summary['unavailable']} unavailable, "
          f"{summary['bars']} observed candles processed.")
    return 1 if summary["unavailable"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
