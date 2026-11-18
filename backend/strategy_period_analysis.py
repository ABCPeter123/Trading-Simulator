"""Private on-demand historical period analysis for one tournament model.

Uses the same signed/cash backtest engine as the portfolio tournament.
No future candles enter signal decisions. The user's candidate universe,
parameters, trades and results stay in private local storage.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from datetime import date, datetime, timezone
import math
from statistics import mean
from fastapi import HTTPException

from . import portfolio_research as pr, advanced_portfolio_research as adv
from . import tournament_strategies as tournament, universe_research as universe


def validate_request(payload):
    if not isinstance(payload, dict):
        raise HTTPException(422, "Invalid period analysis request.")
    spec = tournament.validate_spec(payload.get("spec"))
    begin, end = payload.get("start_date"), payload.get("end_date")
    def parse(value, label):
        if value is None or value == "":
            return None
        if not isinstance(value, str) or len(value) != 10:
            raise HTTPException(422, f"Invalid {label}; use YYYY-MM-DD.")
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise HTTPException(422, f"Invalid {label}; use YYYY-MM-DD.") from None
        if parsed.year < 1980:
            raise HTTPException(422, f"{label} must be in or after 1980.")
        return parsed
    start_date, end_date = parse(begin, "start_date"), parse(end, "end_date")
    if start_date and end_date and start_date > end_date:
        raise HTTPException(422, "Start date must not exceed end date.")
    if start_date and start_date > datetime.now(timezone.utc).date():
        raise HTTPException(422, "Cannot backtest a future start date.")
    if end_date and end_date > datetime.now(timezone.utc).date():
        raise HTTPException(422, "Cannot backtest beyond today's historical observations.")
    # These are temporary study overrides; the saved model remains immutable.
    cap = payload.get("max_position_pct", spec["max_position_pct"])
    delay = payload.get("delay_sessions", spec["delay_sessions"])
    slippage = payload.get("slippage_bps", universe.COST_ASSUMPTIONS["slippage_bps"])
    if type(cap) not in (int, float) or not math.isfinite(cap) or not 10 <= cap <= 50:
        raise HTTPException(422, "Maximum asset weight must be between 10% and 50%.")
    if type(delay) is not int or delay not in (1, 2):
        raise HTTPException(422, "Execution delay must be one or two shared sessions.")
    if type(slippage) not in (int, float) or not math.isfinite(slippage) or not 0 <= slippage <= 100:
        raise HTTPException(422, "Slippage must be between zero and 100 basis points.")
    standard = spec["model"] in pr.MODELS
    exposure_supplied = any(k in payload for k in
                            ("target_investment_pct","equity_class_cap_pct","redistribute_excess"))
    if exposure_supplied and not standard:
        raise HTTPException(422,"Custom investment and equity concentration targets currently apply to long-only standard models. Advanced models retain their own leverage and hedge budgets.")
    target = payload.get("target_investment_pct",95.)
    equity = payload.get("equity_class_cap_pct",70.)
    redistribute = payload.get("redistribute_excess",False)
    if standard:
        if type(target) not in (int,float) or not math.isfinite(target) or not 5<=target<=100:
            raise HTTPException(422,"Investment target must be between 5% and 100%.")
        if type(equity) not in (int,float) or not math.isfinite(equity) or not 10<=equity<=100:
            raise HTTPException(422,"Equity category cap must be between 10% and 100%.")
        if type(redistribute) is not bool:
            raise HTTPException(422,"Redistribution setting must be a boolean.")
    return {
        "spec": spec, "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "max_position_pct": float(cap), "delay_sessions": delay,
        "slippage_bps": float(slippage),
        **({"target_investment_pct":float(target),
            "equity_class_cap_pct":float(equity),
            "redistribute_excess":redistribute} if standard else {}),
    }


def _period_metrics(curve, capital):
    """Monthly and worst rolling returns on completed, marked account equity."""
    if not curve:
        raise ValueError("Cannot analyze an empty equity curve.")
    monthly = []
    base = capital
    period = None
    for bar in curve:
        month = datetime.fromtimestamp(int(bar["time"]), timezone.utc).strftime("%Y-%m")
        if month != period:
            if monthly:
                previous = monthly[-1]
                previous["return_pct"] = round((previous["ending_equity"] / base - 1)*100, 4)
                previous["pnl_usd"] = round(previous["ending_equity"]-base,2)
                base = previous["ending_equity"]
            monthly.append({"month": month, "ending_equity": float(bar["value"]),
                            "return_pct": None, "pnl_usd":None,
                            "observed_sessions": 0})
            period = month
        monthly[-1]["ending_equity"] = float(bar["value"])
        monthly[-1]["observed_sessions"] += 1
    monthly[-1]["return_pct"] = round((monthly[-1]["ending_equity"] / base - 1)*100, 4)
    monthly[-1]["pnl_usd"] = round(monthly[-1]["ending_equity"]-base,2)
    # Only full rolling market-session windows are eligible for a worst-case value.
    amounts = [float(bar["value"]) for bar in curve]
    observed = [capital, *amounts]
    def worst(horizon):
        if len(observed) <= horizon:
            return None
        bad = min(
            ((observed[end]/observed[end-horizon]-1)*100, end)
            for end in range(horizon, len(observed))
            if observed[end-horizon] > 0
        )
        end_idx = bad[1]-1
        start_idx = max(0,end_idx-horizon+1)
        return {"return_pct": round(bad[0],4),
                "start": datetime.fromtimestamp(int(curve[start_idx]["time"]),timezone.utc).date().isoformat(),
                "end": datetime.fromtimestamp(int(curve[end_idx]["time"]),timezone.utc).date().isoformat(),
                "sessions":horizon}
    peak=capital;worst_drawdown={"drawdown_pct":0., "peak_date":None, "trough_date":None}
    peak_date=None
    for bar in curve:
        val=float(bar["value"])
        if val>peak:
            peak=val;peak_date=datetime.fromtimestamp(int(bar["time"]),timezone.utc).date().isoformat()
        dd=(val/peak-1)*100
        if dd<worst_drawdown["drawdown_pct"]:
            worst_drawdown={"drawdown_pct":round(dd,4),"peak_date":peak_date,
                            "trough_date":datetime.fromtimestamp(int(bar["time"]),timezone.utc).date().isoformat()}
    return {
        "monthly":monthly,
        "best_month":max(monthly,key=lambda x:x["return_pct"]),
        "worst_month":min(monthly,key=lambda x:x["return_pct"]),
        "monthly_average_pct":round(mean(x["return_pct"] for x in monthly),4),
        "positive_months":sum(x["return_pct"]>0 for x in monthly),
        "observed_months":len(monthly),
        "worst_day":worst(1),
        "worst_five_sessions":worst(5),
        "worst_21_sessions":worst(21),
        "worst_drawdown":worst_drawdown,
    }


def analyze(params, *, loader=None, report=None):
    """Run an isolated historical simulation with explicit selected date limits."""
    params = validate_request(params)
    report = report or (lambda pct, stage: None)
    spec=params["spec"]
    symbols=spec["symbols"]
    histories={}
    for index,symbol in enumerate(symbols):
        report(5+int(index*35/max(len(symbols),1)), "Loading historical market observations")
        try:
            histories[symbol]= (loader or universe._read)(symbol)
        except (HTTPException,ValueError,KeyError,TypeError,OSError) as exc:
            raise ValueError("Historical data unavailable for a portfolio member") from exc
    if any(pr.get_instrument(s).currency=="CAD" for s in symbols):
        report(43,"Loading verified currency history")
        histories["usdcad"]=(loader or universe._read)("usdcad")
    report(50,"Aligning completed observations")
    dates, market, metadata, source=pr._prepare(symbols,histories)
    start=bisect_left(dates,params["start_date"]) if params["start_date"] else pr.WARMUP
    end=bisect_right(dates,params["end_date"]) if params["end_date"] else len(dates)
    if start<pr.WARMUP:
        raise ValueError(
            "Requested start precedes the 180-session indicator warmup; "
            f"the earliest possible start for this basket is {dates[pr.WARMUP]}.")
    if end-start<5:
        raise ValueError("Selected period has fewer than five eligible shared trading sessions.")
    report(60,"Executing strategy with historical opening prices")
    broker={**universe.COST_ASSUMPTIONS,
            "delay_sessions":params["delay_sessions"],
            "slippage_bps":params["slippage_bps"]}
    if spec["model"] in pr.MODELS:
        broker.update(target_investment_pct=params["target_investment_pct"],
                      equity_class_cap_pct=params["equity_class_cap_pct"],
                      redistribute_excess=params["redistribute_excess"])
    segment=adv.segment if spec["model"] in adv.MODELS else pr._segment
    metrics=segment(spec["model"],symbols,market,metadata,start,end,
                    params["max_position_pct"]/100,broker=broker)
    report(75,"Calculating historical risk and benchmark")
    basis=_period_metrics(metrics["equity_curve"],pr.STARTING_CAPITAL)
    # An identical date window, cost model and per-asset cap for the baseline.
    benchmark=pr._segment("equal_weight",symbols,market,metadata,start,end,
                          params["max_position_pct"]/100,broker=broker)
    # Execution-delay stress always uses a slower setup and >= 20 bps slippage.
    stress_broker={**broker,"delay_sessions":2,
                   "slippage_bps":max(20.,params["slippage_bps"])}
    stressed=segment(spec["model"],symbols,market,metadata,start,end,
                     params["max_position_pct"]/100,broker=stress_broker)
    report(95,"Preparing private period report")
    compact_keys=("return_pct","max_drawdown_pct","annualized_volatility_pct",
                  "sharpe","sortino","trades","fees","turnover_pct",
                  "average_invested_pct","average_gross_exposure_pct",
                  "average_net_exposure_pct","peak_gross_leverage",
                  "margin_interest","short_borrow_cost","margin_calls")
    return {
        "requested_window":{"start_date":params["start_date"],"end_date":params["end_date"]},
        "actual_window":{"start_date":dates[start],"end_date":dates[end-1],
                         "sessions":end-start,"warmup_sessions":pr.WARMUP,
                         "available_start":dates[0],"available_end":dates[-1]},
        "model":spec["model"],"research_only":spec["model"] in adv.RESEARCH_ONLY,
        "assumptions":{**broker,"max_position_pct":params["max_position_pct"],
                       "rebalance_sessions":pr.REBALANCE_SESSIONS,
                       "starting_capital":pr.STARTING_CAPITAL},
        "metrics":{key:metrics.get(key) for key in compact_keys},
        "benchmark":{key:benchmark.get(key) for key in compact_keys},
        "execution_stress":{key:stressed.get(key) for key in compact_keys},
        "periods":basis,
        "equity_curve":metrics["equity_curve"],
        "benchmark_curve":benchmark["equity_curve"],
        "fills":metrics["executions"][:200],
        "fills_total":len(metrics["executions"]),
        "sources":source,
        "limitations":[
            "Selected-period evaluation is exploratory and not an independent out-of-sample test.",
            "Worst observed daily/monthly/rolling outcomes are historical, not a statistical maximum loss or future forecast.",
            "Actual trading outcomes can differ because of spreads, dividends, corporate actions, borrow availability, liquidity, fees, taxes and intraday price changes.",
            "All instruments are aligned to common observed sessions. A 180-session price-history warmup is required before the first simulation trade.",
            "Each custom run starts from the same virtual capital with zero positions; holdings do not carry over from a tournament segment.",
        ],
    }
