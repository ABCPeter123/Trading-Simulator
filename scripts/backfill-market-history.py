"""Owner-only local, rate-limited historical OHLCV backfill.

Provider data is never committed. CLI operates only in local research mode.
By default downloads 20 years (or as much as the provider has) of daily
history for a diversified public reference list. No private strategy input.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import market, intraday  # noqa: E402
from backend.archive import archive_path, archive_stats  # noqa: E402
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


def target_ids(preset: str | None, ids: str, limit: int,
               all_catalog: bool = False) -> list[str]:
    if all_catalog and (preset or ids.strip()):
        raise ValueError("Use --all on its own, not with --preset or --ids.")
    choices = ([item["id"] for item in list_instruments(limit=2000)
                if get_instrument(item["id"]).ticker]
               if all_catalog else list(PRESETS[preset]) if preset else [])
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



# One widest available window per actual candle interval. We never download
# 10Y, 15Y and 20Y *as well as* MAX during a single "everything" run.
# Likewise we avoid storing 7D, 30D and 60D copies of the same 5m candles.
BULK_INTRADAY = (
    ("1m", "7D"), ("5m", "60D"), ("15m", "60D"), ("1h", "2Y"),
)


def download_plan(ids: list[str], window: str,
                  include_intraday: bool = False) -> list[tuple[str, str, str]]:
    """Each task has a unique asset, interval and maximum desired time window."""
    if window not in ("10Y", "15Y", "20Y", "MAX"):
        raise ValueError("Unsupported daily window.")
    tasks = []
    for asset_id in dict.fromkeys(ids):
        instrument = get_instrument(asset_id)
        if not instrument.ticker:
            continue  # Undated option placeholder cannot have real bars
        tasks.append((asset_id, "1d", window))
        if include_intraday and instrument.kind != "Funds":
            tasks.extend((asset_id, res, span) for res, span in BULK_INTRADAY)
    return tasks


def _progress_path() -> Path:
    return Path(os.environ.get(
        "TRADING_SIM_MARKET_DIR", ROOT / "data" / "market"
    )) / "_download_progress.json"


def _read_progress(path: Path) -> dict:
    if not path.is_file():
        return {"version": 1, "completed": {}}
    saved = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(saved, dict) or saved.get("version") != 1 or not isinstance(
        saved.get("completed"), dict
    ):
        raise ValueError("Invalid download checkpoint. No data was changed.")
    return saved


def _write_progress(path: Path, progress: dict) -> None:
    """Durable checkpoint: crash cannot partially overwrite prior progress."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(progress, separators=(",", ":")), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _existing_stats(asset_id: str, period: str, resolution: str) -> dict | None:
    """A present file is only complete if it contains readable observed bars."""
    key = period if resolution == "1d" else f"{period}_{resolution}"
    if not archive_path(asset_id, key).is_file():
        return None
    try:
        stats = archive_stats(asset_id, key)
        return stats if stats["bars"] > 0 else None
    except Exception:
        # If the local archive cannot be read, do NOT silently overwrite it.
        raise ValueError("Existing local archive is unreadable; manual repair required.")


def backfill_catalog(
    ids: list[str], window: str, delay: float, include_intraday: bool = False,
    refresh: bool = False, checkpoint: Path | None = None,
    fetch_daily=market.history, fetch_intraday=intraday.replay_history,
    pause=time.sleep, emit=print,
) -> dict:
    """Resume safely. Skip previously archived asset+resolution+window tasks.

    Existing archives are checked even if the progress JSON was removed.
    Refresh is explicit and writes via archive.record_history, whose timestamp
    uniqueness constraint merges corrections without duplicate OHLCV rows.
    """
    tasks = download_plan(ids, window, include_intraday)
    path = checkpoint if checkpoint is not None else _progress_path()
    progress = _read_progress(path)
    result = {"requested": len(tasks), "downloaded": 0, "skipped_existing": 0,
              "offline_only": 0, "unavailable": 0, "bars": 0}
    for index, (asset_id, resolution, period) in enumerate(tasks, 1):
        archive_key = period if resolution == "1d" else f"{period}_{resolution}"
        key = f"{asset_id}|{resolution}|{period}"
        try:
            existing = _existing_stats(asset_id, period, resolution)
            if existing and not refresh:
                result["skipped_existing"] += 1
                if key not in progress["completed"]:
                    progress["completed"][key] = {
                        "bars": existing["bars"], "first": existing["first_timestamp"],
                        "last": existing["last_timestamp"],
                    }
                    _write_progress(path, progress)
                emit(f"[{index}/{len(tasks)}] {asset_id} {archive_key}: "
                     f"skipped {existing['bars']} already-archived bars.")
                continue
            response = (fetch_daily(asset_id, period) if resolution == "1d"
                        else fetch_intraday(asset_id, period, resolution))
            observed = response["bars"]
            if not observed or response.get("is_demo"):
                raise ValueError("No real OHLCV observations available.")
            if response.get("offline_cache"):
                result["offline_only"] += 1
                emit(f"[{index}/{len(tasks)}] {asset_id} {archive_key}: offline archive only.")
                continue
            # Normal provider adapters store the validated bars in local
            # Parquet. A successful network response is NOT success unless
            # the corresponding on-disk archive is readable.
            recorded = _existing_stats(asset_id, period, resolution)
            if not recorded:
                raise OSError("Source returned observations but none were archived.")
            progress["completed"][key] = {
                "bars": recorded["bars"], "first": recorded["first_timestamp"],
                "last": recorded["last_timestamp"],
            }
            _write_progress(path, progress)
            result["downloaded"] += 1
            result["bars"] += recorded["bars"]
            first = datetime.fromtimestamp(recorded["first_timestamp"], timezone.utc).date()
            last = datetime.fromtimestamp(recorded["last_timestamp"], timezone.utc).date()
            emit(f"[{index}/{len(tasks)}] {asset_id} {archive_key}: saved "
                 f"{recorded['bars']} unique candles, {first} through {last}.")
        except Exception as exc:
            result["unavailable"] += 1
            # Don't echo provider URLs, request headers, local owner paths,
            # credentials, holdings or private strategy data.
            emit(f"[{index}/{len(tasks)}] {asset_id} {archive_key}: "
                 f"unavailable ({type(exc).__name__}); safe to retry.")
        if index < len(tasks) and delay > 0:
            pause(delay)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local-only historical market data backfill.")
    parser.add_argument("--all", dest="all_catalog", action="store_true",
                        help="Include all known catalog instruments with provider tickers.")
    parser.add_argument("--include-intraday", action="store_true",
                        help="Also download widest available minute/hour intervals.")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-fetch completed tasks; merge bars by unique timestamp.")
    parser.add_argument("--preset", choices=tuple(PRESETS))
    parser.add_argument("--ids", default="", help="Comma-separated local catalog IDs")
    parser.add_argument("--window", choices=("10Y", "15Y", "20Y", "MAX"),
                        help="Daily window, default MAX for --all, 20Y otherwise.")
    parser.add_argument("--limit", type=int,
                        help="Max instruments; default all for --all, 50 otherwise.")
    parser.add_argument("--delay", type=float, default=0.75,
                        help="Seconds between requests, range 0.25 to 30.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO") == "1":
        parser.error("Bulk owner data operations are disabled in public demo mode.")
    maximum = args.limit if args.limit is not None else (2000 if args.all_catalog else 50)
    if not 1 <= maximum <= 2000:
        parser.error("--limit must be between 1 and 2000")
    if not 0.25 <= args.delay <= 30:
        parser.error("--delay must be 0.25 to 30 seconds")
    window = args.window or ("MAX" if args.all_catalog else "20Y")
    try:
        ids = target_ids(args.preset, args.ids, maximum,
                         all_catalog=args.all_catalog)
        tasks = download_plan(ids, window, args.include_intraday)
    except (HTTPException, ValueError, KeyError):
        parser.error("Unknown ticker, conflicting --all options, or too many instruments.")
    if args.dry_run:
        print(f"Dry run: {len(ids)} catalog IDs, {len(tasks)} distinct download tasks.")
        print(f"Daily window {window}; intraday {'included' if args.include_intraday else 'excluded'}.")
        print(f"Output location: {_progress_path().parent}")
        print("Existing complete Parquet windows will be skipped without refetching.")
        return 0
    print(f"Fetching up to {len(tasks)} public market-data windows into Git-ignored "
          "local Parquet. Actual availability is provider-dependent.")
    try:
        result = backfill_catalog(ids, window, args.delay,
                                  include_intraday=args.include_intraday,
                                  refresh=args.refresh)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Unable to load or create safe checkpoint ({type(exc).__name__}).")
        return 2
    print(f"Finished: {result['downloaded']} downloaded, "
          f"{result['skipped_existing']} skipped existing, "
          f"{result['offline_only']} offline only, "
          f"{result['unavailable']} unavailable, "
          f"{result['bars']} unique recorded bars in downloaded archives.")
    return 1 if result["unavailable"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
