"""Offline research tournament and broker execution regression coverage.

No real owner data, provider calls, broker orders, or future OHLCV leaks.
"""
from datetime import datetime, timedelta, timezone
import math

import pytest
from fastapi.testclient import TestClient

from backend import universe_research as ur, portfolio_research as pr, assets
from backend.main import app


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(ur,"DB_PATH",tmp_path/"universe.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    return tmp_path


def synthetic(days=1150):
    start=datetime(2020,1,1,tzinfo=timezone.utc)
    rows=[]
    for i in range(days):
        stamp=start+timedelta(days=i)
        if stamp.weekday()>4:continue
        px=70*(1+.00035)**i*(1+.013*math.sin(i/19))
        rows.append({"time":int(stamp.timestamp()),"open":px*1.0002,
                     "high":px*1.015,"low":px*.985,"close":px,
                     "volume":10000+i})
    return rows


def test_private_universe_queue_durable_and_cancellable(isolated):
    client=TestClient(app)
    job=client.post("/api/live/research/universe/jobs",json={
        "scope":"etfs","delay_sessions":1,"max_drawdown_pct":35,
        "max_position_pct":30})
    assert job.status_code==202,job.text
    id=job.json()["id"]
    assert job.json()["status"]=="queued"
    assert client.get("/api/live/research/universe/jobs").json()[0]["id"]==id
    assert client.get("/api/live/research/universe/jobs/"+id).json()["result"] is None
    assert client.post("/api/live/research/universe/jobs/"+id+"/cancel").json()["status"]=="cancelled"
    assert ur.process_one() is None


def test_only_actual_consistent_ohlcv_can_enter_tournament():
    rows=synthetic()
    assert ur._quality(rows)
    assert not ur._quality(rows[:200])
    assert not ur._quality([*rows,dict(rows[-1])])
    assert not ur._quality([*rows[:-1],{**rows[-1],"high":0}])
    assert "spy" in ur._universe("all")
    assert "spy" in ur._universe("etfs")
    assert "spy" not in ur._universe("stocks")


def test_run_study_uses_validation_and_reports_unavailable_assets(isolated,monkeypatch):
    base=synthetic()
    # Reduce fixture universe while preserving a realistic mixed basket.
    chosen=["spy","qqq","ief","gld","eem","vnq","vti","xlv","tlt","shy"]
    monkeypatch.setattr(ur,"_universe",lambda scope:chosen)
    calls=[]
    def loader(s):
        calls.append(s)
        if s=="vnq":raise ValueError("Missing provider data")
        return {"source":"Synthetic offline testing only","bars":base}
    result=ur.run_study({"scope":"all","delay_sessions":1,
        "max_drawdown_pct":60,"max_position_pct":40},loader=loader)
    assert result["screened_count"]==10
    assert result["excluded_count"]==1
    assert result["exclusions"]["vnq"]=="missing_or_invalid_ohlcv"
    assert 1<=len(result["top10"])<=10
    assert result["test_used_for_selection"] is False
    assert result["qualified_candidates"] >= len(result["top10"])
    assert all(x["validation_score"]>=y["validation_score"]
               for x,y in zip(result["top10"],result["top10"][1:]))
    assert result["shortlist_is_global_top_ten"] is True
    assert "leveraged_trend" in result["candidate_model_counts"]
    assert "long_short_momentum" in result["candidate_model_counts"]
    assert result["historical_coverage"]["universe_earliest_session"] is not None
    for pick in result["top10"]:
        assert pick["no_real_order"] is True
        assert "validation_quality_label" in pick
        assert "same_basket_underperformance_points" in pick["score_breakdown"]["components"]
        assert pick["rank"]>=1
        assert "held_out" in pick
        assert "validation_regimes" in pick
        assert pick["coverage"]["common_sessions"]>=450
        assert pick["hypothetical_scenarios"]["status"] in (
            "hypothetical_resampled_history","insufficient_observations")
    assert set(calls)==set(chosen)


def test_cash_backtest_applies_wealthismple_cost_and_latency_stress():
    # Use exactly pre-provided historical sessions; no backend or exchange calls.
    bars=synthetic(days=1300)
    model="equal_weight"
    market={"spy":bars,"ief":bars}
    metadata={s:{"group":"equity" if s=="spy" else "bond",
        "currency":"USD","spread_bps":5,"kind":"ETFs"} for s in market}
    baseline=pr._segment(model,list(market),market,metadata,pr.WARMUP,
                         len(bars),.40)
    zero=pr._segment(model,list(market),market,metadata,pr.WARMUP,
        len(bars),.40,broker={"commission_usd":0,"fx_conversion_bps":0,
        "slippage_bps":2,"base_currency":"USD","delay_sessions":1})
    fx=pr._segment(model,list(market),market,metadata,pr.WARMUP,
        len(bars),.40,broker={"commission_usd":0,"fx_conversion_bps":150,
        "slippage_bps":8,"base_currency":"CAD","delay_sessions":2})
    assert baseline["fees"]>zero["fees"]
    assert fx["fees"]>zero["fees"]
    assert fx["ending_equity"]!=zero["ending_equity"]
    assert set(x["execution"] for x in fx["executions"])=={"second_session_open"}
    assert zero["trades"]>0


def test_scenarios_are_deterministic_but_not_real_predictions():
    curve=[{"time":i,"value":100000*(1+.0006*i+math.sin(i/10)*.007)}
           for i in range(100)]
    one=ur._scenarios(curve,9)
    two=ur._scenarios(curve,9)
    assert one==two
    assert one["status"]=="hypothetical_resampled_history"
    assert len(one["paths"])==16
    assert {p["horizon_sessions"] for p in one["paths"]}=={10,30,60,120}
    assert all(x["p05_return_pct"]<=x["p95_return_pct"] for x in one["paths"])


def test_no_universe_research_in_public_demo(isolated,monkeypatch):
    monkeypatch.setenv("TRADING_SIM_PUBLIC_DEMO","1")
    with pytest.raises(Exception):
        ur.enqueue()
    assert ur.process_one() is None



def test_tournament_queue_preserves_weekly_cadence_and_rejects_unsupported(isolated):
    client=TestClient(app)
    post=client.post("/api/live/research/universe/jobs",json={
        "scope":"all","rebalance_sessions":5})
    assert post.status_code==202,post.text
    assert post.json()["params"]["rebalance_sessions"]==5
    for bad in (0,2,3,22,True,1.0):
        res=client.post("/api/live/research/universe/jobs",json={
            "scope":"all","rebalance_sessions":bad})
        assert res.status_code==422



def test_validation_penalty_prefers_same_basket_outperformance():
    control={"return_pct":14.}
    ref={"excess_sharpe":.72}
    weak={"return_pct":8.}
    quality={"excess_sharpe":.41}
    penalty,detail=ur._same_basket_validation_penalty(weak,quality,control,ref)
    assert penalty>6.
    assert detail["excess_return_points"]==-6.
    assert detail["excess_sharpe_delta"]==pytest.approx(-.31)
    assert not detail["beats_same_basket_return"]
    assert not detail["beats_same_basket_risk_adjusted"]
    improved,better=ur._same_basket_validation_penalty(
        {"return_pct":20.},{"excess_sharpe":1.1},control,ref)
    assert improved==0.
    assert better["beats_same_basket_return"]
    assert better["beats_same_basket_risk_adjusted"]
    missing,info=ur._same_basket_validation_penalty(weak,quality,None,None)
    assert missing==0. and info is None


def test_actual_shortlist_is_global_validation_top_ten_only(isolated,monkeypatch):
    """Ranking cannot reserve low-score families or peek at held-out prices."""
    initial=synthetic()
    changed=[dict(bar) for bar in initial]
    for bar in changed[int(len(changed)*.81):]:
        bar["open"]*=.75
        bar["close"]*=.75
        bar["high"]*=.75
        bar["low"]*=.75
    symbols=["spy","qqq","ief","gld","vti","xlp"]
    monkeypatch.setattr(ur,"_universe",lambda _:symbols)
    def scan(rows):
        return ur.run_study({"scope":"all","delay_sessions":1,
            "max_drawdown_pct":60,"max_position_pct":40},
            loader=lambda _:{"bars":rows,"source":"Independent synthetic fixture"})
    before=scan(initial)
    after=scan(changed)
    assert before["shortlist_is_global_top_ten"] is True
    assert [(x["model"],x["symbols"],x["validation_score"])
            for x in before["top10"]]==[
            (x["model"],x["symbols"],x["validation_score"])
            for x in after["top10"]]
    assert all(x["score_breakdown"]["components"][
        "same_basket_underperformance_points"]<=0 for x in before["top10"])


def test_balanced_ranking_debits_unstable_validation_windows():
    valid={"return_pct":16.,"max_drawdown_pct":-8.,
           "turnover_pct":95.,"annualized_volatility_pct":14.,"trades":20}
    regimes={"worst_regime_return_pct":-10.}
    stable={"sufficient_history":True,"window_count":3,"positive_windows":3}
    unstable={**stable,"positive_windows":1}
    strong=ur._balanced_breakdown(valid,regimes,stable)
    weak=ur._balanced_breakdown(valid,regimes,unstable)
    assert strong["components"]["losing_validation_windows_points"]==0
    assert weak["components"]["losing_validation_windows_points"]==-16
    assert strong["total"]-weak["total"]==pytest.approx(16)
