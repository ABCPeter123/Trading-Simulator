"""Private intraday multi-asset research on actual synchronized provider candles.

Separate from daily tournament and its walk-forward results. The selected
cash-funded allocation model is re-evaluated on completed intraday candles,
with an open of the NEXT candle used for fills. No invented minute bars.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import floor, isfinite, sqrt
from statistics import mean
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from . import portfolio_research as pr
from . import intraday
from .assets import get_instrument

NY = ZoneInfo("America/New_York")
WINDOWS = {
    "1m": ("7D",),
    "5m": ("7D", "30D", "60D"),
    "15m": ("7D", "30D", "60D"),
    "1h": ("7D", "30D", "60D", "6M", "1Y", "2Y"),
}
BARS_PER_SESSION = {"1m": 390, "5m": 78, "15m": 26, "1h": 7}
STEP_SECONDS = intraday.SECONDS
CHECKS = {
    1: ((12, 0),),
    2: ((11, 0), (14, 0)),
    4: ((10, 30), (12, 0), (13, 30), (15, 0)),
}
MAX_BARS = 20000


def validate_request(payload):
    spec = payload["spec"]
    if spec["model"] not in pr.MODELS:
        raise HTTPException(422, "Intraday research currently supports cash-funded standard portfolio models only.")
    if any(get_instrument(s).currency != "USD" or
           get_instrument(s).kind not in ("Stocks", "ETFs")
           for s in spec["symbols"]):
        raise HTTPException(422, "Intraday portfolio research currently requires USD stocks and ETFs.")
    if spec.get("base_currency", "USD") != "USD":
        raise HTTPException(422, "Use a USD research account for intraday tests; intraday CAD funding is not modeled.")
    resolution = payload.get("resolution", "5m")
    period = payload.get("period", "60D")
    checks = payload.get("checks_per_day", 2)
    slippage = payload.get("slippage_bps", spec.get("slippage_bps", 8.))
    commission = payload.get("commission_usd", spec.get("commission_usd", 0.))
    if resolution not in WINDOWS or period not in WINDOWS[resolution]:
        raise HTTPException(422, "Unavailable intraday resolution or provider lookback window.")
    if type(checks) is not int or checks not in CHECKS:
        raise HTTPException(422, "Choose one, two, or four intraday checks per market day.")
    if type(slippage) not in (int, float) or not isfinite(slippage) or not 0 <= slippage <= 100:
        raise HTTPException(422, "Invalid intraday slippage.")
    if type(commission) not in (int, float) or not isfinite(commission) or not 0 <= commission <= 30:
        raise HTTPException(422, "Invalid per-order commission.")
    return {"spec": spec, "mode": "intraday", "resolution": resolution,
            "period": period, "checks_per_day": checks,
            "slippage_bps": float(slippage), "commission_usd": float(commission)}


def _time(bar):
    return datetime.fromtimestamp(int(bar["time"]), NY)


def _prepare(params, load, now):
    spec = params["spec"]
    symbols = spec["symbols"]
    arrays = {}
    sources = {}
    for symbol in symbols:
        payload = load(symbol, params["period"], params["resolution"])
        if payload.get("is_demo"):
            raise ValueError("Demo candle data cannot enter private intraday research.")
        bars = payload.get("bars")
        if not isinstance(bars, list) or len(bars) < pr.WARMUP + 30 or len(bars) > MAX_BARS:
            raise ValueError("Not enough bounded provider intraday bars for this portfolio.")
        available = {}
        previous = -1
        for bar in bars:
            timestamp = int(bar["time"])
            if timestamp <= previous or not intraday._valid(bar):
                raise ValueError("Non-chronological or invalid provider candle.")
            previous = timestamp
            local = _time(bar)
            minute = local.hour * 60 + local.minute
            # Only completed regular-session candles. Exclude pre/post-market.
            if (timestamp + STEP_SECONDS[params["resolution"]] > now.timestamp()
                    or local.weekday() > 4 or not 570 <= minute < 960):
                continue
            available[timestamp] = bar
        arrays[symbol] = available
        sources[symbol] = {"source": str(payload.get("source", "unknown"))[:120],
                           "offline_snapshot": bool(payload.get("offline_cache")),
                           "observed_bars": len(available)}
    shared = sorted(set.intersection(*(set(x) for x in arrays.values())))
    if len(shared) < pr.WARMUP + 30:
        raise ValueError("Insufficient exactly synchronized completed intraday bars; no candles were forward-filled.")
    market = {s: [arrays[s][ts] for ts in shared] for s in symbols}
    metadata = {s: {"kind": get_instrument(s).kind,
                    "group": pr._group(s, get_instrument(s).kind),
                    "spread_bps": float(get_instrument(s).spread_bps),
                    "currency": "USD"} for s in symbols}
    return shared, market, metadata, sources


def _schedule(shared, checks):
    days = defaultdict(list)
    for index, stamp in enumerate(shared):
        if index >= pr.WARMUP:
            days[_time({"time":stamp}).date().isoformat()].append(index)
    chosen = set()
    for indices in days.values():
        for hour,minute in CHECKS[checks]:
            target = hour*60 + minute
            matching = next((index for index in indices
                             if (lambda dt: dt.hour*60+dt.minute)(
                                 _time({"time":shared[index]})) >= target), None)
            if matching is not None:
                chosen.add(matching)
    return chosen


def _simulate(spec, shared, market, metadata, checks, slippage, commission, model):
    symbols = spec["symbols"]
    closes = {s: [float(bar["close"]) for bar in market[s]] for s in symbols}
    capital = pr.STARTING_CAPITAL
    cash = capital
    holdings = {s: 0 for s in symbols}
    max_weight = float(spec["max_position_pct"]) / 100
    gross_target = float(spec.get("target_investment_pct", 95)) / 100
    equity_cap = float(spec.get("equity_class_cap_pct", 70)) / 100
    redistribute = bool(spec.get("redistribute_excess", False))
    timestamps = _schedule(shared, checks)
    orders = []
    marks = []
    total_fees = 0.
    invested_total = 0.
    peak = capital
    worst_drawdown = 0.
    checked = 0
    yearly_bars = BARS_PER_SESSION[model["resolution"]] * 252

    for i in range(pr.WARMUP, len(shared)):
        opens = {s: float(market[s][i]["open"]) for s in symbols}
        if i in timestamps:
            # At candle i OPEN, only completed candles 0...i-1 may be read.
            weights = pr._weights(model["name"], symbols, closes, i, metadata,
                                  max_weight, gross_target=gross_target,
                                  equity_cap=equity_cap, redistribute=redistribute,
                                  annualization_periods=yearly_bars)
            if (set(weights) != set(symbols) or any(not isfinite(w) or w < -1e-9
                   or w > max_weight + 1e-8 for w in weights.values())
                    or sum(weights.values()) > gross_target + 1e-8):
                raise ValueError("Intraday target breaches long-only allocation limits.")
            total = cash + sum(holdings[s]*opens[s] for s in symbols)
            for side in ("sell", "buy"):
                for s in symbols:
                    half_spread = float(metadata[s]["spread_bps"]) / 2
                    fill = opens[s]*(1+(1 if side=="buy" else -1)*(half_spread+slippage)/10000)
                    wanted = floor(max(0., weights[s]*total/fill))
                    delta = wanted - holdings[s]
                    if side=="sell":
                        qty = max(0, -delta)
                    else:
                        qty = min(max(0, delta), floor(max(0., cash-commission-1)/fill))
                    if qty <= 0:
                        continue
                    fee = commission
                    if side=="sell":
                        cash += qty*fill-fee
                        holdings[s] -= qty
                    else:
                        cash -= qty*fill+fee
                        holdings[s] += qty
                    total_fees += fee
                    orders.append({"time": shared[i], "symbol": s, "side": side,
                                   "quantity": qty, "price": round(fill, 5),
                                   "fee": fee, "notional": round(qty*fill, 2)})
            checked += 1
        value = cash + sum(holdings[s]*closes[s][i] for s in symbols)
        if value <= 0 or not isfinite(value):
            raise ValueError("Invalid intraday portfolio equity.")
        invested_total += sum(holdings[s]*closes[s][i] for s in symbols)/value
        peak = max(peak, value)
        worst_drawdown = min(worst_drawdown, (value/peak-1)*100)
        marks.append({"time": shared[i], "value": round(value, 4)})
    sessions = len({datetime.fromtimestamp(ts, NY).date() for ts in shared[pr.WARMUP:]})
    summary = {"return_pct": round((marks[-1]["value"]/capital-1)*100, 4),
               "max_drawdown_pct": round(worst_drawdown, 4),
               "trades": len(orders), "fees": round(total_fees, 2),
               "turnover_pct": round(sum(o["notional"] for o in orders)/capital*100, 2),
               "average_invested_pct": round(100*invested_total/len(marks), 2),
               "checks": checked, "sessions": sessions}
    return summary, marks, orders


def analyze(params, *, loader=None, report=None, now=None):
    """No fitting or candidate selection; result is exploratory, not unseen proof."""
    params = validate_request(params)
    report = report or (lambda pct, stage: None)
    now = now or datetime.now(timezone.utc)
    provider = loader or intraday.replay_history
    report(5, "Loading actual provider intraday bars")
    shared, market, meta, sources = _prepare(params, provider, now)
    report(60, "Replaying completed-bar portfolio decisions")
    spec = params["spec"]
    model = {"name":spec["model"], "resolution":params["resolution"]}
    selected, curve, fills = _simulate(
        spec, shared, market, meta, params["checks_per_day"],
        params["slippage_bps"], params["commission_usd"], model)
    report(80, "Running same-data, same-cost constrained equal-weight control")
    benchmark, benchmark_curve, _ = _simulate(
        spec, shared, market, meta, params["checks_per_day"],
        params["slippage_bps"], params["commission_usd"],
        {"name":"equal_weight","resolution":params["resolution"]})
    report(98, "Preparing private intraday result")
    def decimate(series):
        step = max(1, (len(series)+499)//500)
        return [*series[::step], *([series[-1]] if (len(series)-1)%step else [])]
    return {
        "mode":"intraday", "resolution":params["resolution"], "period":params["period"],
        "model":spec["model"], "symbols":spec["symbols"],
        "checks_per_day":params["checks_per_day"], "common_bars":len(shared),
        "first_bar":shared[0], "last_bar":shared[-1],
        "warmup_bars":pr.WARMUP,
        "metrics":selected, "benchmark":benchmark,
        "equity_curve":decimate(curve), "benchmark_curve":decimate(benchmark_curve),
        "fills":fills[:150], "fills_total":len(fills),
        "sources":sources,
        "execution":"Signal uses only prior completed intraday closes; fills at next shared candle open with assumed spread, slippage and commission.",
        "limitations":[
            "Exploratory recent-history replay, not a walk-forward selection or sealed independent audit.",
            "The selected daily model is re-evaluated on intraday BAR lookbacks. A 126-bar moving average is not a 126-day moving average.",
            "Only synchronized observed regular-session USD stock/ETF candles are used; missing candles are not invented or forward-filled.",
            "One, two, or four allocation decisions per market day are allowed; a decision may generate no orders or several asset orders.",
            "Annualized return and Sharpe are intentionally omitted for short intraday samples.",
            "Provider minute history is restricted to its published window. Local archived candles are flagged and may be stale.",
            "Modeled next-bar opening fills, spread and slippage are not broker quotes or proof of fillability.",
            "Borrowing, short positions, margin, taxes, dividends and market impact are not modeled. No broker orders are submitted.",
        ]
    }
