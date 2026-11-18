"""Independently synthetic market benchmark and private read-only research review."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from math import sin

from backend import research_review
from backend import walkforward_diagnostics as diag
from backend import walkforward_optimizer as optimizer


def prices(days=1500):
    first=datetime(2018,1,1,tzinfo=timezone.utc)
    out=[]
    for i in range(days):
        d=first+timedelta(days=i)
        if d.weekday()>4:continue
        close=75*(1+.0003)**i*(1+.013*sin(i/26))
        out.append({"time":int(d.timestamp()),"open":close*1.0001,
                    "close":close,"high":close*1.02,
                    "low":close*.98,"volume":8000})
    return out


def settings():
    return {"risk_free_pct":3.,"slippage_bps":8.,"commission_usd":.35,
            "fx_conversion_bps":150.,"base_currency":"USD"}


def test_spy_buy_hold_exact_daily_sessions_with_costs():
    observed=prices()
    market={"ief":[{"time":bar["time"]} for bar in observed]}
    data={"bars":observed,"source":"Synthetic independent price fixture"}
    ref=diag.spy_price_reference(data,market,["ief"],160,400,settings(),
                                 spread_bps=2.)
    assert ref["status"]=="available"
    assert ref["matched_sessions"]==240
    assert ref["method"]=="single_buy_hold_price_only"
    assert ref["selection_used_this_reference"] is False
    assert ref["return_pct"]>0
    assert "dividends" in ref["income_treatment"].lower()
    cad={**settings(),"base_currency":"CAD"}
    changed=diag.spy_price_reference(data,market,["ief"],160,400,cad,spread_bps=2.)
    assert changed["fx_bps_on_buy"]==150
    assert changed["return_pct"]<ref["return_pct"]
    extra={**settings(),"slippage_bps":25.}
    slipped=diag.spy_price_reference(data,market,["ief"],160,400,extra,spread_bps=2.)
    assert slipped["return_pct"]<=ref["return_pct"]


def test_missing_spy_day_never_forward_fills():
    observed=prices()
    market={"qqq":[{"time":bar["time"]} for bar in observed]}
    incomplete=deepcopy(observed)
    del incomplete[200]
    result=diag.spy_price_reference({"bars":incomplete},
                                    market,["qqq"],175,225,settings())
    assert result["status"]=="unavailable"
    assert "return_pct" not in result
    rejected=diag.spy_price_reference({"bars":observed,"is_demo":True},
                                      market,["qqq"],175,225,settings())
    assert rejected["status"]=="unavailable"


def test_audit_shocks_do_not_change_prior_selection_or_proposal_execution():
    baseline=prices()
    crashed=deepcopy(baseline)
    for row in crashed[int(len(crashed)*.85):]:
        for field in ("open","close","high","low"):
            row[field]*=.35
    spec={"version":1,"model":"equal_weight","symbols":["spy","qqq","ief"],
          "max_position_pct":40,"delay_sessions":1,"rebalance_sessions":21,
          "research_only":False,"restricted_research":False,"short_proxy_research":False}
    config={"spec":spec,"search_width":"focused",
            "target_cagr_pct":55.,"target_sharpe":2.,
            "max_drawdown_pct":60.,**settings()}
    result_a=optimizer.analyze(config,loader=lambda _:{"bars":baseline,"source":"Synthetic"})
    result_b=optimizer.analyze(config,loader=lambda _:{"bars":crashed,"source":"Synthetic"})
    assert result_a["status"]==result_b["status"]=="completed"
    assert result_a["final_audit"]["selected"]==result_b["final_audit"]["selected"]
    assert [f["selected"] for f in result_a["walk_forward"]["folds"]]==[
        f["selected"] for f in result_b["walk_forward"]["folds"]]
    assert result_a["model_search"]["pre_audit_selection_diagnostics"]==result_b["model_search"]["pre_audit_selection_diagnostics"]
    assert result_a["final_audit"]["market_benchmark"]["status"]=="available"
    assert result_a["final_audit"]["market_benchmark"]["return_pct"]!=result_b["final_audit"]["market_benchmark"]["return_pct"]
    review=result_a["research_review"]
    assert review["status"]=="diagnostic_only"
    assert review["integrity"]["selection_changed"] is False
    assert review["integrity"]["experiments_queued"]==0
    assert review["integrity"]["broker_orders"]==0
    assert all(p["automatic_execution"] is False for p in review["next_experiments"])
    assert all(x["basis"] in ("sealed_audit","pre_audit_walkforward","pre_audit_only")
               for x in review["findings"])


def test_review_can_be_called_without_market_benchmark_on_old_report():
    report={"status":"completed","targets":{"risk_free_pct":3.},
            "walk_forward":{"folds":[{"selected":{"model":"equal_weight"}}]},
            "model_search":{"pre_audit_candidate_leaderboard":{
                "eligible_count":1,"attempted_count":4}},
            "final_audit":{"selected":{"model":"equal_weight"},
                           "objectives":{"cagr_pct":1.,"excess_sharpe":-.3},
                           "return_pct":4.,"benchmark_comparison":{"benchmarks":[]},
                           "exposure_and_costs":{"average_gross_invested_pct":45.,
                                                 "turnover_pct_of_initial_capital":350.}}}
    output=research_review.review(report)
    codes={x["code"] for x in output["findings"]}
    assert "below_cash_hurdle" in codes
    assert "nonpositive_excess_sharpe" in codes
    assert "low_invested_exposure" in codes
    assert "high_turnover_weak_growth" in codes
    assert "few_eligible_training_models" in codes
    assert output["status"]=="diagnostic_only"
    assert research_review.review({"status":"insufficient_history"})["status"]=="unavailable"
