"""Validation-only single practical candidate selection.

This is a conservative, explicit ranking of simulated portfolios, NOT tax
advice, evidence of live profitability, or a broker execution guarantee.
The final sealed audit must never be inspected here.
"""
from __future__ import annotations
import math

from . import advanced_portfolio_research as adv

UNSUITABLE_LONG_PRODUCTS = frozenset((
    "tqqq","sqqq","upro","spxu","cweb","vixy",
))
STARTING_CAPITAL = 100000.


def realized_gain_reserve(executions, tax_rate_pct):
    """Illustrative reserve on positive realized trade gains.

    Average acquisition cost of bought shares. No credit for losses, no tax
    laws assumed. This must NOT be added to the already-net-of-cost equity
    line as though it were an actual tax payment.
    """
    quantity, cost = {}, {}
    profitable = 0.
    for event in executions:
        symbol = str(event["symbol"])
        qty = float(event["quantity"])
        price = float(event["price"])
        fee = float(event.get("fee",0))
        if qty<=0 or price<=0 or not all(math.isfinite(x) for x in (qty,price,fee)):
            raise ValueError("Invalid simulated transaction for tax proxy.")
        prev = quantity.get(symbol,0.)
        avg = cost.get(symbol,0.)
        if event["side"]=="buy":
            new=prev+qty
            cost[symbol]=(prev*avg+qty*price+fee)/new
            quantity[symbol]=new
        elif event["side"]=="sell":
            if qty>prev+1e-5:
                # Signed-share models are excluded from executable selection.
                raise ValueError("Short position is not cash-tradable.")
            gain=qty*(price-avg)-fee
            profitable+=max(0.,gain)
            quantity[symbol]=max(0.,prev-qty)
        else:
            raise ValueError("Invalid transaction side.")
    return round(profitable*tax_rate_pct/100.,2)


def evaluate(candidate, *, max_drawdown_pct=30., tax_rate_pct=25.,
             base_currency="USD", require_delay_stress=True):
    """Return inspectable practical score; None for an untradeable model.

    Inputs must be pre-audit selection observations ONLY. Lower cash taxes
    depend on account registration and user's individual facts, not code.
    """
    model=candidate["model"]
    symbols=candidate["symbols"]
    # Actual Wealthsimple currently cannot execute short shares via this
    # model; derivatives and highly levered exchange-traded products need
    # different margin, suitability and risk verification.
    if (model in adv.RESEARCH_ONLY or any(s in UNSUITABLE_LONG_PRODUCTS for s in symbols)
            or candidate.get("train",{}).get("margin_calls",0)):
        return None
    validation=candidate["validation"]
    quality=candidate["validation_objectives"]
    sharpe=quality.get("excess_sharpe")
    if sharpe is None or not math.isfinite(sharpe):
        return None
    if (not math.isfinite(float(validation["max_drawdown_pct"])) or
            abs(validation["max_drawdown_pct"])>max_drawdown_pct):
        return None
    stress=candidate.get("validation_execution_stress")
    if require_delay_stress and stress is None:
        return None
    if stress is not None and abs(float(stress["max_drawdown_pct"]))>max_drawdown_pct:
        return None
    # Real simulation already deducts modeled spread/slippage/commission/FX
    # and (where applicable) borrow/funding charges.
    reserve=realized_gain_reserve(validation.get("executions",[]),tax_rate_pct)
    tax_pct=reserve/STARTING_CAPITAL*100.
    turnover=max(0.,float(validation.get("turnover_pct",0.)))
    drawdown=abs(float(validation["max_drawdown_pct"]))
    ret=float(validation.get("return_pct",0.))
    stress_loss=max(0.,ret-float(stress["return_pct"])) if stress else 0.
    # Configuration can be transacted by buying stocks/ETFs, but blended
    # portfolios need maintaining multiple simultaneous component rules.
    operational=8. if candidate.get("sleeves") else 0.
    fx_assets=sum(candidate.get("_metadata",{}).get(s,{}).get("currency",base_currency)
                  !=base_currency for s in symbols)
    operational+=5. if fx_assets else 0.
    gap=(candidate.get("validation_benchmark_advantage") or {}).get("excess_return_points")
    # High priority: risk-adjusted net validation performance and drawdown.
    # The stated tax rate is a *sensitivity input* on realized gains, not a
    # legally determined rate. No unknown future news or unseen prices enter.
    components={
        "excess_sharpe_points":round(90.*sharpe,4),
        "drawdown_points":round(-2.2*drawdown,4),
        "turnover_points":round(-.025*turnover,4),
        "delayed_fill_points":round(-1.8*stress_loss,4),
        "tax_reserve_points":round(-2.0*tax_pct,4),
        "operational_friction_points":-operational,
        "benchmark_underperformance_points":round(-.5*max(0.,-float(gap)),4)
                                              if gap is not None else -10.,
    }
    return {
        "score":round(sum(components.values()),4),
        "score_components":components,
        "validation_excess_sharpe":sharpe,
        "validation_drawdown_pct":validation["max_drawdown_pct"],
        "delayed_fill_return_loss_pct":round(stress_loss,4),
        "estimated_tax_reserve_usd":reserve,
        "tax_assumption_pct":tax_rate_pct,
        "tax_method":"Conservative positive-realized-sale average-cost sensitivity; NOT a tax liability or after-tax backtest.",
        "operation":"cash long-only manual ETF/share trades; blended sleeves require extra monitoring"
                    if candidate.get("sleeves") else "cash long-only manual ETF/share trades",
        "cross_currency_asset_count":fx_assets,
        "requires_usd_balance":base_currency=="USD",
        "benchmark_return_gap_pct":gap,
        "tradeability":"manual_cash_portfolio",
        "selection_data":"historical validation only; final audit excluded",
    }


def choose(candidates, *, max_drawdown_pct=30., tax_rate_pct=25.,
           base_currency="USD", require_delay_stress=True):
    ranked=[]
    for row in candidates:
        diagnostic=evaluate(row,max_drawdown_pct=max_drawdown_pct,
                            tax_rate_pct=tax_rate_pct,base_currency=base_currency,
                            require_delay_stress=require_delay_stress)
        if diagnostic is not None:
            ranked.append((diagnostic["score"],row,diagnostic))
    if not ranked:
        return None,{"eligible":0,"reason":"no_cash_executable_validation_candidate"}
    ranked.sort(key=lambda item:(-item[0],item[1]["basket_type"],item[1]["model"]))
    _,selected,decision=ranked[0]
    edge=selected.get("validation_benchmark_advantage") or {}
    decision["demonstrated_edge"]=(
        decision["validation_excess_sharpe"]>0 and
        edge.get("beats_same_basket_return",False) and
        edge.get("beats_same_basket_risk_adjusted",False) and
        (selected.get("validation_stability") or {}).get("positive_windows",0)>=2)
    decision["recommendation_status"]=(
        "research_candidate_requires_paper_forward"
        if decision["demonstrated_edge"] else
        "no_demonstrated_trading_edge"
    )
    return selected,{"eligible":len(ranked),"selected":decision,
                      "reason":"single_best_validation_sharpe_drawdown_executable_cost_rank"}
