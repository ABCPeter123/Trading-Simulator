"""Read-only portfolio diagnostics for private walk-forward research.

All benchmark models run on the exact same aligned historical session range.
Cash is a *fixed-rate hypothetical hurdle* and is not credited to the strategy.
Attribution measurements describe backtested exposures, never broker activity.
No audit results are used for selecting a strategy.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from math import isfinite
from . import portfolio_research as portfolio, performance_objectives as objectives

GROUPS=("equity","bond","commodity","real_estate","crypto")


def exposure(result, symbols, metadata):
    """Trading cost and exposure diagnostics using a segment's own ledger.

    'rebalances' are discrete weight snapshots, NOT every session's holdings.
    Average invested comes from the segment's daily marked gross exposure.
    """
    samples=result.get("rebalances") or []
    groups=defaultdict(list)
    cash_snapshots=[]
    concentration=[]
    for row in samples:
        weights=row.get("weights") or {}
        for group in GROUPS:
            groups[group].append(sum(
                abs(float(weight))*100 for symbol,weight in weights.items()
                if metadata[symbol]["group"]==group
            ))
        if "cash_pct" in row:
            cash_snapshots.append(float(row["cash_pct"]))
        # Gross concentration among absolute occupied weights; it does not
        # confuse signed net exposure with gross investment.
        gross=sum(abs(float(w)) for w in weights.values())
        if gross>1e-12:
            concentration.append(max(abs(float(w)) for w in weights.values())/gross*100)
    execution_rows=result.get("executions",result.get("trades",[]))
    return {
        "starting_capital_usd":float(result.get("starting_capital",portfolio.STARTING_CAPITAL)),
        "ending_equity_usd":result.get("ending_equity"),
        "average_gross_invested_pct":result.get("average_gross_exposure_pct",
                                                result.get("average_invested_pct")),
        "average_net_exposure_pct":result.get("average_net_exposure_pct",
                                              result.get("average_invested_pct")),
        "average_rebalance_cash_pct":round(sum(cash_snapshots)/len(cash_snapshots),2)
                                        if cash_snapshots else None,
        "final_cash_pct":result.get("cash_pct"),
        "average_category_gross_pct":{
            group:round(sum(values)/len(values),2) for group,values in groups.items()
            if values
        },
        "average_largest_position_share_of_gross_pct":
            round(sum(concentration)/len(concentration),2) if concentration else None,
        "position_snapshots":len(samples),
        "snapshot_definition":"At executed rebalance opens only; daily average exposure is separate.",
        "turnover_pct_of_initial_capital":result.get("turnover_pct"),
        "explicit_fees_and_financing_usd":result.get("fees"),
        "transaction_fees_usd":result.get("transaction_fees"),
        "margin_interest_usd":result.get("margin_interest",0.),
        "short_borrow_cost_usd":result.get("short_borrow_cost",0.),
        "trade_count":result.get("trades") if isinstance(result.get("trades"),int) else len(execution_rows),
        "turnover_interpretation":"Gross executed buy/sell notional divided by virtual starting capital, not annualized.",
    }


def _cash_hurdle(market, symbols, start, stop, risk_free_pct):
    if not (0 <= risk_free_pct <= 15) or not isfinite(risk_free_pct):
        raise ValueError("Invalid illustrative cash yield.")
    baseline=portfolio.STARTING_CAPITAL
    daily=(1+risk_free_pct/100)**(1/252)
    return [
        {"time":market[symbols[0]][i]["time"],
         "value":round(baseline*daily**(i-start+1),4)}
        for i in range(start,stop)
    ]


def baseline_comparison(selected, symbols, market, metadata, start, stop,
                        max_weight, settings, *, reference_segment=None):
    """Compare a fixed same-basket equal-weight implementation and cash hurdle.

    Never use these comparisons for training model selection or selection
    between already-audited candidates. No extra market data are fabricated.
    """
    broker={"base_currency":settings["base_currency"],
            "commission_usd":settings["commission_usd"],
            "fx_conversion_bps":settings["fx_conversion_bps"],
            "slippage_bps":settings["slippage_bps"],
            "delay_sessions":settings["spec"]["delay_sessions"],
            "target_investment_pct":95.,
            "equity_class_cap_pct":70.,
            "redistribute_excess":False}
    reference=reference_segment or portfolio._segment(
        "equal_weight",symbols,market,metadata,start,stop,max_weight,broker=broker)
    cash=_cash_hurdle(market,symbols,start,stop,settings["risk_free_pct"])
    benchmarks=[]
    for kind,label,curve,return_pct in (
        ("same_basket_equal_weight",
         "Constrained equal weight, same instruments, 95% target and 70% equity cap",
         reference["equity_curve"],reference["return_pct"]),
        ("constant_cash_hurdle",
         "Illustrative constant annual cash yield, not an investable historical cash series",
         cash,(cash[-1]["value"]/portfolio.STARTING_CAPITAL-1)*100)):
        quality=objectives.performance(curve,risk_free_pct=settings["risk_free_pct"])
        benchmarks.append({
            "id":kind,"name":label,
            "return_pct":round(return_pct,4),
            "cagr_pct":quality["cagr_pct"],
            "excess_sharpe":quality["excess_sharpe"],
            "drawdown_pct":_max_drawdown(curve),
            "volatility_pct":quality["annualized_volatility_pct"],
            "excess_return_vs_selected_pct_points":round(return_pct-selected["return_pct"],4),
        })
    return {"benchmarks":benchmarks,
            "selected_return_pct":selected["return_pct"],
            "reproducible_comparison":True,
            "limitations":[
                "Equal-weight benchmark uses exactly the same instruments and time window, not an external broad-market index.",
                "Benchmark resets at the beginning of each segment, as the strategy does.",
                "Cash hurdle assumes a constant user-specified annual rate, with no simulated cash ledger, market-dependent rates, taxes, or account fees.",
                "Cash hurdle is an illustration, not a known actual cash return over the historical interval.",
                "Benchmark performance must not be used to reselect a strategy after opening the audit.",
            ]}


def _max_drawdown(curve):
    peak=portfolio.STARTING_CAPITAL
    worst=0.
    for row in curve:
        peak=max(peak,float(row["value"]))
        worst=min(worst,(float(row["value"])/peak-1)*100)
    return round(worst,4)


def candidate_leaderboard(eligible, rejected, total, *, limit=5):
    """Pre-audit training candidate diagnostics, no future observation access."""
    leaders=sorted(eligible,key=lambda x:(-x["score"],x["order"]))[:limit]
    return {
        "eligible_count":len(eligible),
        "attempted_count":total,
        "rejected_count":total-len(eligible),
        "rejection_reasons":dict(sorted(Counter(rejected).items())),
        "best_by_training_score":[{
            "rank":i+1,
            "config":record["config"],
            "training_score":round(record["score"],4),
            "training_cagr_pct":record["quality"]["cagr_pct"],
            "training_excess_sharpe":record["quality"]["excess_sharpe"],
            "training_drawdown_pct":record["drawdown"],
            "training_turnover_pct":record["turnover"],
            "training_average_invested_pct":record["invested"],
            "score_components":record["score_details"]["components"],
        } for i,record in enumerate(leaders)],
        "basis":"Training prices before fold boundary only. Final audit data excluded."
    }


def parameter_sensitivity(selected_config, symbols, market, metadata, end,
                          settings, executor):
    """Small pre-audit cap perturbations; report outcomes, never reselect.

    The final held-out bars are never read. Do not claim a new holdout after
    tuning to the results of this diagnostic or the previously seen audit.
    """
    chosen=float(selected_config["max_position_pct"])
    runs=[]
    for change in (-5.,0.,5.):
        cap=max(10.,min(50.,chosen+change))
        if any(x["max_position_pct"]==cap for x in runs):
            continue
        alternative={**selected_config,"max_position_pct":cap}
        try:
            outcome=executor(alternative,symbols,market,metadata,
                             portfolio.WARMUP,end,settings["slippage_bps"],settings)
            quality=objectives.performance(
                outcome["equity_curve"],risk_free_pct=settings["risk_free_pct"])
            runs.append({
                "max_position_pct":cap,"selected_setting":cap==chosen,
                "cagr_pct":quality["cagr_pct"],
                "excess_sharpe":quality["excess_sharpe"],
                "drawdown_pct":outcome["max_drawdown_pct"],
                "turnover_pct":outcome.get("turnover_pct"),
            })
        except (ValueError,ArithmeticError,ZeroDivisionError):
            runs.append({"max_position_pct":cap,"selected_setting":cap==chosen,
                         "error":"invalid_candidate_on_prior_history"})
    numeric=[x["cagr_pct"] for x in runs if isinstance(x.get("cagr_pct"),(int,float))]
    return {"cap_perturbation_pct_points":5.,
            "pre_audit_only":True,
            "variants":runs,
            "cagr_range_pct_points":round(max(numeric)-min(numeric),4)
                                     if len(numeric)>=2 else None,
            "interpretation":"Prior-only local parameter neighborhood; informational, never used to reselect the audited portfolio."}
