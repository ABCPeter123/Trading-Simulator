"""Synthetic-only regression checks for blended, shared-cash portfolio models."""
from datetime import datetime, timedelta, timezone
import math

import pytest

from backend import portfolio_research as pr
from backend import blended_portfolio_research as blend
from backend import performance_objectives as objectives
from backend import walkforward_optimizer as wf
from backend.tests.test_walkforward_optimizer import request,spec


def fixture(n=520):
    start=datetime(2017,1,2,tzinfo=timezone.utc)
    times=[int((start+timedelta(days=i)).timestamp()) for i in range(n)]
    symbols=["spy","qqq","ief","gld"]
    market={}
    for j,s in enumerate(symbols):
        market[s]=[{"time":t,"open":p*1.001,"close":p}
                   for i,t in enumerate(times)
                   for p in [70*(1.0002**i)*(1+.01*math.sin(i/(14+j*5)))]]
    meta={s:{"group":"bond" if s=="ief" else ("commodity" if s=="gld" else "equity"),
             "kind":"ETFs","spread_bps":5.,"currency":"USD"} for s in symbols}
    return symbols,market,meta


def sleeves():
    return [{"model":"relative_momentum","weight_pct":50},
            {"model":"inverse_volatility","weight_pct":50}]


def test_blend_rejects_short_margin_and_bad_weights():
    for bad in (
        [{"model":"long_short_momentum","weight_pct":50},
         {"model":"trend_filter","weight_pct":50}],
        [{"model":"trend_filter","weight_pct":60},
         {"model":"inverse_volatility","weight_pct":60}],
        [{"model":"trend_filter","weight_pct":50},
         {"model":"trend_filter","weight_pct":50}],
        [{"model":"relative_momentum","weight_pct":100}],
    ):
        with pytest.raises(ValueError):
            blend.validate_sleeves(bad)


def test_blend_uses_shared_cash_net_orders_and_never_borrows():
    symbols,market,meta=fixture()
    broker={"target_investment_pct":100,"equity_class_cap_pct":100,
            "redistribute_excess":True,"delay_sessions":1,
            "slippage_bps":8,"commission_usd":0,
            "fx_conversion_bps":0,"base_currency":"USD"}
    result=blend.segment(sleeves(),symbols,market,meta,180,440,.40,broker=broker)
    assert len(result["equity_curve"])==260
    assert result["ending_equity"]>0
    assert result["research_only"] is True
    assert all(x["side"] in ("buy","sell") for x in result["executions"])
    assert all(sum(x["weights"].values())<=1.00001 and x["cash_pct"]>=-1e-6
               for x in result["rebalances"])
    assert all(max(x["weights"].values())<=.4001 for x in result["rebalances"])
    # Every ticker is rebalanced as a net order, not repeated sleeve-specific
    # buys/sells with duplicated fees in the same session.
    session_symbol=[(x["time"],x["symbol"]) for x in result["executions"]]
    assert len(session_symbol)==len(set(session_symbol))


def test_blended_signals_ignore_future_prices():
    symbols,market,meta=fixture()
    prices={s:[x["close"] for x in market[s]] for s in symbols}
    old=blend.blend_weights(sleeves(),symbols,prices,240,meta,.40,1.,1.,True)
    later={s:[*v] for s,v in prices.items()}
    for values in later.values():
        for j in range(240,len(values)):values[j]*=20
    new=blend.blend_weights(sleeves(),symbols,later,240,meta,.40,1.,1.,True)
    assert old==new
    assert sum(old.values())<=1.+1e-9
    assert max(old.values())<=.40+1e-9


def test_blend_global_equity_cap_and_signal_cash_limit():
    symbols,market,meta=fixture()
    prices={s:[x["close"] for x in market[s]] for s in symbols}
    target=blend.blend_weights(sleeves(),symbols,prices,240,meta,.40,.95,.55,False)
    assert target["spy"]+target["qqq"]<=.55+1e-9
    assert sum(target.values())<=.95+1e-9
    assert all(x>=0 for x in target.values())


def test_wide_search_contains_real_blended_candidate():
    samples=list(wf.candidates(spec(),"focused"))
    extended=list(wf.candidates(spec(),"extended"))
    assert len(samples)==12
    assert len(extended)==24
    mixes=[s for s in samples if s["model"]=="blended_portfolio"]
    assert mixes
    assert all(2<=len(x["sleeves"])<=3 for x in mixes)
    assert all(sum(s["weight_pct"] for s in x["sleeves"])==100 for x in mixes)
    signed=list(wf.candidates(spec("leveraged_trend"),"focused"))
    assert not any(x["model"]=="blended_portfolio" for x in signed)


def dated_curve(first,last,per_session=.001):
    begin=datetime(first,1,2,tzinfo=timezone.utc)
    end=datetime(last,12,30,tzinfo=timezone.utc)
    capital=100000.;rows=[]
    while begin<=end:
        if begin.weekday()<5:
            capital*=1+per_session
            rows.append({"time":int(begin.timestamp()),"value":capital})
        begin+=timedelta(days=1)
    return rows


def test_rolling_years_and_partial_years_are_not_invented():
    rows=dated_curve(2020,2022)
    p=objectives.consistency(rows,target_cagr_pct=50)
    assert p["rolling_windows"]==len(rows)-251
    assert p["worst_rolling_12m_pct"] is not None
    assert p["complete_calendar_years"]>=2
    assert p["worst_complete_calendar_year_pct"] is not None
    assert all(y["return_pct"]>0 for y in p["calendar_years"])
    partial=objectives.consistency(rows[:130],target_cagr_pct=50)
    assert partial["rolling_windows"]==0
    assert partial["worst_rolling_12m_pct"] is None
    assert partial["worst_complete_calendar_year_pct"] is None
    assert partial["complete_calendar_years"]==0


def test_blended_research_ui_has_annual_consistency_metrics():
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    ui=(root/"src"/"WalkForwardOptimizer.tsx").read_text(encoding="utf-8")
    assert 'value.model==="blended_portfolio"' in ui
    assert "Worst rolling 12-month return" in ui
    assert "Partial year" in ui
