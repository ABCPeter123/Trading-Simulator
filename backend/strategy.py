"""Bar-close SMA crossover with next-bar-open execution, no future bars in signals."""
from decimal import Decimal
from fastapi import HTTPException

from .assets import get_instrument
from .ledger import fee_for, modeled_fill
from .market import history

def sma_backtest(asset_id: str, fast: int = 10, slow: int = 30) -> dict:
    instrument = get_instrument(asset_id)
    if not instrument.tradable or instrument.currency != "USD":
        raise HTTPException(422, detail="Backtests currently support USD cash instruments only.")
    if not 2 <= fast < slow <= 100:
        raise HTTPException(422, detail="Require 2 <= fast < slow <= 100.")
    candles = history(asset_id, "1Y")["bars"]
    if len(candles) < slow + 3:
        raise HTTPException(422, detail="Not enough price bars to evaluate this strategy.")
    cash = Decimal("10000")
    shares = Decimal(0)
    curve = []
    trades = []
    closes = [Decimal(str(c["close"])) for c in candles]
    for i, bar in enumerate(candles):
        # Signal uses data through prior bar close (i-1); execute at bar i open.
        if i >= slow + 1:
            fast_prev = sum(closes[i-fast-1:i-1]) / fast
            slow_prev = sum(closes[i-slow-1:i-1]) / slow
            fast_curr = sum(closes[i-fast:i]) / fast
            slow_curr = sum(closes[i-slow:i]) / slow
            side = ("buy" if fast_prev <= slow_prev and fast_curr > slow_curr else
                    "sell" if fast_prev >= slow_prev and fast_curr < slow_curr else None)
            if side and (side == "buy" and shares == 0 or side == "sell" and shares > 0):
                reference = Decimal(str(bar["open"]))
                proxy = {"price": float(reference), "bid": None, "ask": None, "spread_bps": instrument.spread_bps}
                fill = modeled_fill(side, proxy)
                if side == "buy":
                    # Whole shares for stocks and ETFs; base units to 6 decimals otherwise.
                    budget = cash * Decimal(".99")
                    if instrument.kind in ("Stocks", "ETFs"):
                        qty = (budget / (fill * Decimal("1.002"))).to_integral_value(rounding="ROUND_FLOOR")
                    else:
                        qty = (budget / (fill * Decimal("1.008"))).quantize(Decimal(".000001"), rounding="ROUND_FLOOR")
                    if qty > 0:
                        fee = fee_for(instrument.kind, qty, fill)
                        if qty * fill + fee <= cash:
                            cash -= qty * fill + fee
                            shares += qty
                            trades.append({"time": bar["time"], "side": side, "quantity": float(qty), "fill": float(fill), "fee": float(fee)})
                else:
                    fee = fee_for(instrument.kind, shares, fill)
                    cash += shares * fill - fee
                    trades.append({"time": bar["time"], "side": side, "quantity": float(shares), "fill": float(fill), "fee": float(fee)})
                    shares = Decimal(0)
        equity = cash + shares * Decimal(str(bar["close"]))
        curve.append({"time": bar["time"], "value": float(equity)})
    final_equity = curve[-1]["value"]
    baseline = (closes[-1] / closes[0] - 1) * 100
    peak = 0.0
    worst = 0.0
    for point in curve:
        peak = max(peak, point["value"])
        if peak: worst = min(worst, (point["value"] / peak - 1) * 100)
    return {
        "asset_id": asset_id, "strategy": "SMA crossover", "fast": fast, "slow": slow,
        "starting_cash": 10000, "ending_equity": final_equity,
        "return_pct": (final_equity / 10000 - 1) * 100,
        "buy_hold_pct": float(baseline), "max_drawdown_pct": worst,
        "trades": trades, "equity_curve": curve,
        "execution": "signal at prior candle close, simulated fill at next candle open with modeled spread, 2bps slippage, and fees",
        "data_source": history(asset_id, "1Y")["source"],
    }
