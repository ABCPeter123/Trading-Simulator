"""Synthetic-only regression coverage for private date-scoped backtests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from backend import strategy_period_analysis as analysis
from backend import strategy_period_queue as queue
from backend import portfolio_research as portfolio
from backend.main import app


def fixture_spec(model="equal_weight"):
    return {"version":1,"model":model,"symbols":["spy","qqq"],
            "max_position_pct":50,"delay_sessions":1,"rebalance_sessions":21,
            "research_only":False,"restricted_research":False,
            "short_proxy_research":False}


def synthetic_rows(trend=0.0005):
    day=datetime(2019,1,1,tzinfo=timezone.utc)
    out=[]
    for i in range(1400):
        moment=day+timedelta(days=i)
        if moment.weekday()>4:
            continue
        price=100*(1+trend)**i*(1+.007*math.sin(i/14))
        out.append({"time":int(moment.timestamp()),"open":price*1.0002,
                    "close":price,"low":price*.97,
                    "high":price*1.03,"volume":10000})
    return out


@pytest.fixture
def offline(monkeypatch,tmp_path):
    records={"spy":synthetic_rows(),"qqq":synthetic_rows(0.0003)}
    def load(name):
        return {"source":"Synthetic test fixture","bars":records[name]}
    monkeypatch.setattr(analysis.universe,"_read",load)
    monkeypatch.setattr(queue,"DB_PATH",tmp_path/"private_periods.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    return records


def base_request(**kw):
    return {"spec":fixture_spec(),**kw}


def test_fully_invested_custom_run_respects_user_limits(offline):
    common=offline["spy"]
    start=datetime.fromtimestamp(common[280]["time"],timezone.utc).date().isoformat()
    end=datetime.fromtimestamp(common[500]["time"],timezone.utc).date().isoformat()
    default=analysis.analyze(base_request(start_date=start,end_date=end))
    invested=analysis.analyze(base_request(
        start_date=start,end_date=end,
        target_investment_pct=100,equity_class_cap_pct=100,
        max_position_pct=50,redistribute_excess=True))
    assert default["actual_window"]["start_date"]==start
    assert default["actual_window"]["end_date"]==end
    assert invested["actual_window"]["sessions"]==221
    assert default["metrics"]["average_invested_pct"]<75
    assert invested["metrics"]["average_invested_pct"]>95
    assert invested["metrics"]["average_invested_pct"] > default["metrics"]["average_invested_pct"]
    assert invested["assumptions"]["target_investment_pct"]==100
    assert invested["assumptions"]["redistribute_excess"] is True
    assert invested["fills_total"]>0
    assert len(invested["periods"]["monthly"])>=9
    assert all(x["pnl_usd"] is not None and x["observed_sessions"]>0
               for x in invested["periods"]["monthly"])
    assert sum(x["pnl_usd"] for x in invested["periods"]["monthly"]) == pytest.approx(
        invested["equity_curve"][-1]["value"]-portfolio.STARTING_CAPITAL,abs=0.05)
    assert invested["periods"]["worst_day"]["return_pct"] <= invested["periods"]["worst_21_sessions"]["return_pct"]+200
    assert invested["metrics"]["annualized_volatility_pct"] is not None
    assert len(invested["equity_curve"])==len(invested["benchmark_curve"])


def test_date_validation_and_lookahead_guards(offline):
    for req in (base_request(start_date="2030-01-01"),
                base_request(start_date="2019-11-01",end_date="2019-01-01"),
                base_request(start_date="2021-13-01"),
                base_request(equity_class_cap_pct=125),
                base_request(target_investment_pct=101),
                base_request(redistribute_excess="true")):
        with pytest.raises(HTTPException) as ex:
            analysis.analyze(req)
        assert ex.value.status_code==422
    with pytest.raises(ValueError,match="warmup"):
        analysis.analyze(base_request(start_date="2019-01-02"))


def test_volatility_target_never_bypasses_risk_filter_for_full_investment(offline):
    request=base_request(target_investment_pct=100,equity_class_cap_pct=100,
                         max_position_pct=50,redistribute_excess=True)
    request["spec"]=fixture_spec("volatility_target")
    result=analysis.analyze(request)
    assert result["metrics"]["average_invested_pct"]<=100.01
    assert result["model"]=="volatility_target"


def test_private_queue_runs_and_preserves_result_across_polling(offline):
    response=TestClient(app).post("/api/live/research/strategy-period/jobs",json=base_request(
        target_investment_pct=100,equity_class_cap_pct=100,
        redistribute_excess=True))
    assert response.status_code==202,response.text
    ident=response.json()["id"]
    assert response.json()["status"]=="queued"
    finished=queue.process_one()
    assert finished["id"]==ident and finished["status"]=="completed",finished
    stored=TestClient(app).get("/api/live/research/strategy-period/jobs/"+ident)
    assert stored.status_code==200
    assert stored.json()["result"]["periods"]["monthly"]
    assert stored.json()["result"]["metrics"]["average_invested_pct"]>95


def test_cancelled_queue_job_does_not_run(offline):
    created=TestClient(app).post("/api/live/research/strategy-period/jobs",json=base_request())
    ident=created.json()["id"]
    cancelled=TestClient(app).post(f"/api/live/research/strategy-period/jobs/{ident}/cancel")
    assert cancelled.status_code==200
    assert cancelled.json()["status"]=="cancelled"
    assert queue.process_one() is None


def test_advanced_research_does_not_silently_ignore_investment_override():
    spec={"version":2,"model":"leveraged_trend","symbols":["spy","qqq"],
          "max_position_pct":40,"delay_sessions":1,"rebalance_sessions":21,
          "research_only":True,"restricted_research":False,"short_proxy_research":False}
    with pytest.raises(HTTPException) as ex:
        analysis.validate_request({"spec":spec,"target_investment_pct":100})
    assert ex.value.status_code==422


def test_engine_risk_caps_and_reallocation_do_not_bypass_signal():
    symbols=["spy","qqq"]
    closes={"spy":[100.]*200,"qqq":[100.]*200}
    meta={s:{"group":"equity"} for s in symbols}
    default=portfolio._weights("equal_weight",symbols,closes,180,meta,.5)
    full=portfolio._weights("equal_weight",symbols,closes,180,meta,.5,
                            gross_target=1,equity_cap=1,redistribute=True)
    assert sum(default.values())==pytest.approx(.70)
    assert sum(full.values())==pytest.approx(1.)
    assert max(full.values())<=.5
    rejected=portfolio._weights("trend_filter",symbols,closes,180,meta,.5,
                                gross_target=1,equity_cap=1,redistribute=True)
    assert all(x==0 for x in rejected.values())
