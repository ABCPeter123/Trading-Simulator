"""Synthetic-only walk-forward regression tests. No owner strategy data."""
from __future__ import annotations

from datetime import datetime,timedelta,timezone
from math import sin
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import walkforward_optimizer as optimizer
from backend import walkforward_queue as queue
from backend.main import app


def synthetic(days=1400,shock=False):
    first=datetime(2018,1,1,tzinfo=timezone.utc)
    out=[]
    for index in range(days):
        moment=first+timedelta(days=index)
        if moment.weekday()>4:continue
        px=80*(1.00045**index)*(1+.012*sin(index/22))
        out.append({"time":int(moment.timestamp()),
                    "open":px*1.0002,"high":px*1.03,
                    "low":px*.97,"close":px,"volume":9000+index})
    if shock:
        for index in range(int(len(out)*.8),len(out)):
            for field in ("open","high","low","close"):
                out[index][field]*=.6
    return out


def spec(model="equal_weight"):
    advanced=model not in ("equal_weight","inverse_volatility","trend_filter",
                           "relative_momentum","volatility_target")
    return {"version":2 if advanced else 1,
            "model":model,"symbols":["spy","qqq","ief"],
            "max_position_pct":40,"delay_sessions":1,"rebalance_sessions":21,
            "research_only":model in ("leveraged_trend","long_short_momentum","market_neutral"),
            "restricted_research":False,"short_proxy_research":False}


def request(**kw):
    return {"spec":spec(),"search_width":"focused",
            "target_cagr_pct":55,"target_sharpe":2,
            "risk_free_pct":3,"max_drawdown_pct":60,
            "slippage_bps":8,**kw}


def fixture_loader(shock=False):
    price=synthetic(shock=shock)
    return lambda symbol:{"bars":price,"source":"Independent synthetic OHLCV fixture"}


def test_validation_and_deterministic_bounded_model_grid():
    p=optimizer.validate_request(request())
    configs=list(optimizer.candidates(p["spec"],p["search_width"]))
    assert len(configs)<=12 and len(configs)>=7
    assert configs[0]["model"]=="equal_weight"
    assert any(c["model"]!="equal_weight" for c in configs)
    assert len(configs)==len({str(sorted(c.items())) for c in configs})
    assert len(list(optimizer.candidates(p["spec"],"extended")))>len(configs)
    for bad in (request(search_width="infinite"),request(target_sharpe=99),
                request(risk_free_pct=-1),request(slippage_bps=900)):
        with pytest.raises(HTTPException) as error:
            optimizer.validate_request(bad)
        assert error.value.status_code==422


def test_expanding_walkforward_seals_final_audit():
    normal=optimizer.analyze(request(),loader=fixture_loader())
    revised=optimizer.analyze(request(),loader=fixture_loader(shock=True))
    assert normal["status"]=="completed"
    assert normal["model_search"]["candidate_count"]<=12
    assert normal["model_search"]["total_train_evaluations"]==4*normal["model_search"]["candidate_count"]
    assert normal["walk_forward"]["fold_count"]==3
    assert len(normal["walk_forward"]["folds"])==3
    assert normal["walk_forward"]["aggregate_objectives"]["sessions"]>0
    assert normal["final_audit"]["sessions"]>=126
    assert normal["final_audit"]["start_date"]>normal["walk_forward"]["folds"][-1]["out_of_sample_end"]
    assert [x["selected"] for x in normal["walk_forward"]["folds"]]==[
        x["selected"] for x in revised["walk_forward"]["folds"]]
    assert [x["out_of_sample_return_pct"] for x in normal["walk_forward"]["folds"]]==[
        x["out_of_sample_return_pct"] for x in revised["walk_forward"]["folds"]]
    assert normal["final_audit"]["selected"]==revised["final_audit"]["selected"]
    assert normal["final_audit"]["return_pct"]!=revised["final_audit"]["return_pct"]
    assert normal["no_real_orders"] is True
    assert normal["walk_forward"]["multiplicity_approximation"]["assumed_trials"]==normal["model_search"]["candidate_count"]


def test_insufficient_history_report_does_not_invent_a_favorable_result():
    result=optimizer.analyze(request(),loader=lambda s:{
        "source":"Independent synthetic OHLCV fixture","bars":synthetic(days=780)})
    assert result["status"]=="insufficient_history"
    assert "walk_forward" not in result
    assert result["no_real_orders"]


def test_approximate_trial_adjustment_is_monotone_and_labeled():
    base=optimizer._trial_adjustment(2.,252,5)
    more=optimizer._trial_adjustment(2.,252,30)
    assert more["bonferroni_approx_p"]>=base["bonferroni_approx_p"]
    assert base["raw_approx_p"]<=base["bonferroni_approx_p"]
    assert optimizer._trial_adjustment(None,100,10)["bonferroni_approx_p"] is None


@pytest.fixture
def local_queue(tmp_path,monkeypatch):
    monkeypatch.setattr(queue,"DB_PATH",tmp_path/"walkforward.sqlite3")
    monkeypatch.setattr(optimizer.universe,"_read",fixture_loader())
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)


def test_private_api_queue_executes_and_saves_report(local_queue):
    client=TestClient(app)
    response=client.post("/api/live/research/walkforward/jobs",json=request())
    assert response.status_code==202,response.text
    job=response.json()
    assert job["status"]=="queued"
    assert job["result"] is None
    assert client.get("/api/live/research/walkforward/jobs").json()[0]["id"]==job["id"]
    final=queue.process_one()
    assert final["status"]=="completed",final
    assert final["result"]["status"]=="completed"
    assert client.get(f"/api/live/research/walkforward/jobs/{job['id']}").json()["result"]["final_audit"]["sessions"]>=126


def test_cancellation_blocks_unstarted_study(local_queue):
    client=TestClient(app)
    job=client.post("/api/live/research/walkforward/jobs",json=request()).json()
    cancelled=client.post(f"/api/live/research/walkforward/jobs/{job['id']}/cancel")
    assert cancelled.status_code==200
    assert cancelled.json()["status"]=="cancelled"
    assert queue.process_one() is None


def test_public_demo_never_enqueues_private_optimization(local_queue,monkeypatch):
    from backend import live_routes
    monkeypatch.setattr("backend.main.PUBLIC_DEMO",True)
    resp=TestClient(app).post("/api/live/research/walkforward/jobs",json=request())
    assert resp.status_code==403
