"""Read-only market-data lineage, completeness and observed-bar diagnostics.

Data-quality metrics are properties of recorded provider bars, not assurances
of exchange accuracy. No market prices are fabricated to fill a gap.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException

from .archive import archive_path
from .assets import get_instrument

SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
MAX_GAPS = 16


def analyze(asset_id: str, window: str, resolution: str = "1d") -> dict:
    """Inspect the exact local Parquet snapshot without network/provider calls."""
    import polars as pl

    if resolution not in SECONDS:
        raise HTTPException(422, detail="Unknown candle resolution.")
    item = get_instrument(asset_id)
    key = window if resolution == "1d" else f"{window}_{resolution}"
    path: Path = archive_path(asset_id, key)
    if not path.exists():
        return {"asset_id": asset_id, "window": window, "resolution": resolution,
                "provider": "not downloaded", "bars": 0, "status": "missing",
                "first_bar": None, "last_bar": None, "age_seconds": None,
                "gaps": [], "duplicate_timestamps": 0,
                "coverage_pct": None, "currency": item.currency,
                "note": "No local market snapshot. Request a chart or subscribe to ingestion."}
    try:
        frame = pl.read_parquet(path, columns=["time", "open", "high", "low", "close", "volume"])
    except Exception as exc:
        raise HTTPException(503, detail="Local market archive could not be read.") from exc
    if frame.is_empty():
        return {"asset_id":asset_id,"window":window,"resolution":resolution,"provider":"local archive",
                "bars":0,"status":"missing","first_bar":None,"last_bar":None,
                "age_seconds":None,"gaps":[],"duplicate_timestamps":0,
                "coverage_pct":None,"currency":item.currency}
    frame = frame.sort("time")
    times = frame["time"].to_list()
    count = len(times)
    duplicate = count - len(set(times))
    seconds = SECONDS[resolution]
    gaps = []
    expected = count
    if resolution == "1d":
        # Weekdays only for exchange-listed products. Holidays cannot be inferred
        # from weekday arithmetic and are reported as possible gaps.
        first = datetime.fromtimestamp(times[0], timezone.utc).date()
        last = datetime.fromtimestamp(times[-1], timezone.utc).date()
        if item.kind == "Crypto":
            expected = (last-first).days+1
        else:
            expected = sum((first+timedelta(days=i)).weekday()<5
                           for i in range((last-first).days+1))
        for previous,next_time in zip(times,times[1:]):
            days = (datetime.fromtimestamp(next_time,timezone.utc).date()-
                    datetime.fromtimestamp(previous,timezone.utc).date()).days
            missing = days-1 if item.kind=="Crypto" else sum(
                (datetime.fromtimestamp(previous,timezone.utc).date()+timedelta(days=i)).weekday()<5
                for i in range(1,days))
            if missing and len(gaps)<MAX_GAPS:
                gaps.append({"after":previous,"before":next_time,"missing_estimate":missing})
    else:
        for a,b in zip(times,times[1:]):
            dt=b-a
            # Do not call overnight/weekend gaps a data incident for listed assets.
            if dt>seconds*1.5 and (item.kind=="Crypto" or dt<=seconds*8):
                if len(gaps)<MAX_GAPS:
                    gaps.append({"after":a,"before":b,
                                 "missing_estimate":max(1,round(dt/seconds)-1)})
        if item.kind=="Crypto":
            expected = max(count, int((times[-1]-times[0])/seconds)+1)
        else:
            # Valid intraday session schedule varies across exchanges.
            expected = None
    latest = times[-1]
    age = max(0,int(datetime.now(timezone.utc).timestamp())-latest)
    # Historical completed bars should not be labelled "bad" because the market
    # closed, nor should a cached archive be advertised as a live feed.
    recent_threshold = 3*seconds if item.kind=="Crypto" else max(86400*5,seconds*3)
    return {"asset_id":asset_id,"window":window,"resolution":resolution,
            "provider":"local archived provider bars","currency":item.currency,
            "bars":count,"status":"recent" if age<=recent_threshold else "archived",
            "first_bar":times[0],"last_bar":latest,"age_seconds":age,
            "gaps":gaps,"duplicate_timestamps":duplicate,
            "coverage_pct":round(min(100,100*count/expected),2) if expected else None,
            "note":"Indicative historical coverage. Gaps may be market holidays, halts or missing provider data. No interpolation."}
