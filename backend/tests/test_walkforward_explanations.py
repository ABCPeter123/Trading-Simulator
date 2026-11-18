"""Synthetic-only diagnostics tests. Never import owner research records."""
from datetime import datetime, timedelta, timezone
from math import sin

from backend import walkforward_diagnostics as diagnostic
from backend import portfolio_research as portfolio


def _data():
    start=datetime(2022,1,3,tzinfo=timezone.utc)
    symbols=["spy","ief","gld"]
    metadata={
        "spy":{"group":"equity","spread_bps":2.,"kind":"ETFs","currency":"USD"},
        "ief":{"group":"bond","spread_bps":4.,"kind":"ETFs","currency":"USD"},
        "gld":{"group":"commodity","spread_bps":6.,"kind":"ETFs","currency":"USD"},
    }
    times=[]
    for i in range(660):
        dt=start+timedelta(days=i)
        if dt.weekday()<5:
            times.append(int(dt.timestamp()))
    market={}
    for j,s in enumerate(symbols):
        market[s]=[]
        for i,t in enumerate(times):
            close=(100+j*12)*(1+.00034)**i*(1+.006*sin(i/(18+j)))
            market[s].append({"time":t,"open":close*1.0001,
                              "close":close})
    return symbols,market,metadata


def test_synthetic_benchmark_same_history_and_constant_cash_hurdle():
    symbols,market,metadata=_data()
    settings={"base_currency":"USD","commission_usd":.35,
              "fx_conversion_bps":150.,"slippage_bps":8.,
              "risk_free_pct":3.,
              "spec":{"delay_sessions":1}}
    start,stop=185,340
    selected=portfolio._segment("equal_weight",symbols,market,metadata,
                                start,stop,.4,
                                broker={**settings,"delay_sessions":1})
    report=diagnostic.baseline_comparison(selected,symbols,market,metadata,
                                         start,stop,.4,settings)
    benchmark=report["benchmarks"]
    assert len(benchmark)==2
    assert benchmark[0]["return_pct"]==round(selected["return_pct"],4)
    assert benchmark[1]["cagr_pct"]==3.0
    assert benchmark[1]["drawdown_pct"]==0.
    assert report["reproducible_comparison"]
    assert "constant" in benchmark[1]["name"]


def test_exposure_snapshots_and_costs_reconcile_to_signed_simulator_fields():
    symbols,market,metadata=_data()
    selected=portfolio._segment("equal_weight",symbols,market,metadata,
                                185,340,.4,
                                broker={"target_investment_pct":95.,
                                        "equity_class_cap_pct":70.,
                                        "commission_usd":.35,
                                        "base_currency":"USD","slippage_bps":8.,
                                        "fx_conversion_bps":150.})
    audit=diagnostic.exposure(selected,symbols,metadata)
    assert audit["trade_count"]==selected["trades"]
    assert audit["average_gross_invested_pct"]==selected["average_invested_pct"]
    assert audit["explicit_fees_and_financing_usd"]==selected["fees"]
    assert audit["turnover_pct_of_initial_capital"]==selected["turnover_pct"]
    assert audit["position_snapshots"]==len(selected["rebalances"])
    assert "equity" in audit["average_category_gross_pct"]


def test_candidate_rejection_categories_are_training_only():
    entries=[{
        "order":1,"score":3.,"config":{"model":"equal_weight"},
        "quality":{"cagr_pct":8.,"excess_sharpe":.2},
        "drawdown":-5.,"turnover":35.,"invested":65.,
        "score_details":{"components":{"turnover_points":-.7}}},
        {"order":2,"score":1.,"config":{"model":"trend_filter"},
         "quality":{"cagr_pct":10.,"excess_sharpe":.1},
         "drawdown":-7.,"turnover":20.,"invested":78.,
         "score_details":{"components":{"turnover_points":-.4}}}]
    report=diagnostic.candidate_leaderboard(
        entries,["max_drawdown_limit","no_training_trades"],4)
    assert report["best_by_training_score"][0]["config"]["model"]=="equal_weight"
    assert report["rejected_count"]==2
    assert report["rejection_reasons"]["max_drawdown_limit"]==1
    assert report["basis"].startswith("Training")
