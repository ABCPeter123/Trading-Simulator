"""Read-only analytics for historical Arcade games.

Every calculation stops at the currently revealed candle. Market marks are
taken from observed closes; gaps retain their most recent *revealed* mark.
Performance includes modeled fill fees and cash movements. Benchmarks are
illustrative price-only holdings, without dividends or corporate actions.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import sqrt
from statistics import mean, pstdev

from .arcade import INITIAL_CASH


def _day(timestamp):
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc).date().isoformat()


def _percent(current, prior):
    return (current / prior - 1) * 100 if prior > 0 else None


def build_report(days, daily, asset_ids, start_index, end_index, fills):
    if start_index > end_index:
        raise ValueError("Invalid analytics window")
    # Read observed closes strictly up to start; preserve warmup information.
    last_marks = {}
    start_marks = {}
    for asset_id in asset_ids:
        available = daily[asset_id]
        mark = None
        for day in days[:start_index + 1]:
            if day in available:
                mark = float(available[day]["close"])
        if mark is None or mark <= 0:
            raise ValueError("No valid mark available at season start")
        last_marks[asset_id] = mark
        start_marks[asset_id] = mark

    events = {}
    for fill in fills:
        asset_id = fill.get("asset_id", asset_ids[0])
        if asset_id not in asset_ids:
            continue
        # Fills originate from source candles whose timestamps are already
        # stored in the frozen snapshot, never from a user-controlled price.
        events.setdefault(_day(fill["time"]), []).append(fill)

    quantities = {asset_id: 0.0 for asset_id in asset_ids}
    average = {asset_id: 0.0 for asset_id in asset_ids}
    realized = {asset_id: 0.0 for asset_id in asset_ids}
    cash = float(INITIAL_CASH)
    cumulative_fees = 0.0
    gross_notional = 0.0
    profitable_exits = 0
    losing_exits = 0
    trade_count = 0
    series = []
    executions = []
    benchmark_start = float(INITIAL_CASH)
    asset_baselines = {asset_id: 0.0 for asset_id in asset_ids}

    for day in days[start_index:end_index + 1]:
        for asset_id in asset_ids:
            candle = daily[asset_id].get(day)
            if candle:
                last_marks[asset_id] = float(candle["close"])

        for fill in events.get(day, []):
            asset_id = fill.get("asset_id", asset_ids[0])
            if asset_id not in quantities:
                continue
            qty = float(fill["quantity"])
            price = float(fill["price"])
            fee = float(fill["fee"])
            notional = qty * price
            if fill["side"] == "buy":
                prev = quantities[asset_id]
                new_qty = prev + qty
                average[asset_id] = (prev * average[asset_id] + notional + fee) / new_qty
                quantities[asset_id] = new_qty
                cash -= notional + fee
            else:
                per_trade_pnl = qty * (price - average[asset_id]) - fee
                realized[asset_id] += per_trade_pnl
                if per_trade_pnl > 0:
                    profitable_exits += 1
                else:
                    losing_exits += 1
                quantities[asset_id] = max(0, quantities[asset_id] - qty)
                if quantities[asset_id] < 1e-8:
                    quantities[asset_id] = 0
                    average[asset_id] = 0
                cash += notional - fee
            cumulative_fees += fee
            gross_notional += notional
            trade_count += 1
            executions.append({
                "day": day, "time": int(fill["time"]), "asset_id": asset_id,
                "side": fill["side"], "quantity": qty, "price": price,
                "fee": fee, "notional": notional, "source": fill.get("source", "unknown"),
                "cash_change": -notional-fee if fill["side"] == "buy" else notional-fee,
            })

        exposure = sum(quantities[a] * last_marks[a] for a in asset_ids)
        equity = cash + exposure
        equal_hold = benchmark_start * mean(last_marks[a] / start_marks[a] for a in asset_ids)
        series.append({
            "day": day, "equity": equity, "benchmark": equal_hold,
            "cash": cash, "invested": exposure,
            "return_pct": _percent(equity, benchmark_start),
            "benchmark_pct": _percent(equal_hold, benchmark_start),
            "fee_total": cumulative_fees,
        })
    peak = 0.0
    max_drawdown = 0.0
    daily_returns = []
    previous = None
    for item in series:
        if previous is not None and previous > 0:
            daily_returns.append((item["equity"] / previous - 1))
        previous = item["equity"]
        peak = max(peak, item["equity"])
        item["drawdown_pct"] = (item["equity"] / peak - 1) * 100 if peak else 0
        max_drawdown = min(max_drawdown, item["drawdown_pct"])

    end = series[-1]
    intervals = {}
    for n in (5, 20, 60, 126, 252):
        if len(series) > n:
            prior = series[-1-n]
            intervals[str(n)] = {
                "return_pct": _percent(end["equity"], prior["equity"]),
                "benchmark_pct": _percent(end["benchmark"], prior["benchmark"]),
                "start_day": prior["day"], "end_day": end["day"],
            }
        else:
            intervals[str(n)] = None

    # The annualized Sharpe uses 252 observed steps per year only if this
    # basket is equity-only. For crypto/weekend mixed calendars report instead
    # a dimensionless per-step Sharpe to avoid unsupported annualization.
    step_sharpe = None
    if len(daily_returns) >= 3:
        sigma = pstdev(daily_returns)
        if sigma > 1e-12:
            step_sharpe = mean(daily_returns) / sigma
    allocations = []
    for asset_id in asset_ids:
        invested = quantities[asset_id] * last_marks[asset_id]
        allocations.append({
            "asset_id": asset_id,
            "quantity": quantities[asset_id],
            "average_cost": average[asset_id],
            "last_close": last_marks[asset_id],
            "invested": invested,
            "weight_pct": invested / end["equity"] * 100 if end["equity"] else 0,
            "realized_pnl": realized[asset_id],
            "unrealized_pnl": quantities[asset_id] * (last_marks[asset_id] - average[asset_id]),
            "price_return_pct": _percent(last_marks[asset_id], start_marks[asset_id]),
            "last_observed_day": next(
                (d for d in reversed(days[start_index:end_index + 1]) if d in daily[asset_id]),
                days[start_index],
            ),
        })

    return {
        "start_day": days[start_index], "end_day": days[end_index],
        "sessions": len(series), "curve": series,
        "summary": {
            "total_return_pct": end["return_pct"],
            "benchmark_return_pct": end["benchmark_pct"],
            "excess_return_pct": end["return_pct"] - end["benchmark_pct"],
            "max_drawdown_pct": max_drawdown,
            "current_equity": end["equity"],
            "current_cash": end["cash"],
            "current_invested": end["invested"],
            "total_fees": cumulative_fees,
            "total_notional_traded": gross_notional,
            "fill_count": trade_count,
            "winning_exits": profitable_exits, "losing_exits": losing_exits,
            "profitable_exit_rate_pct": 100 * profitable_exits / (profitable_exits + losing_exits)
                if profitable_exits + losing_exits else None,
            "step_sharpe": step_sharpe,
        },
        "rolling": intervals,
        "allocations": allocations,
        "executions": executions,
        "methodology": (
            "Historical, price-only equal-weight buy-and-hold benchmark; each "
            "asset receives an equal starting notional and is marked at last "
            "revealed close. Strategy equity reconstructs actual modeled fills "
            "and fees. Rolling returns use shared replay timeline steps, not "
            "calendar-day returns. No dividends, splits, interest, cash flows, "
            "market impact, risk-free-rate or real exchange fills."
        ),
    }
