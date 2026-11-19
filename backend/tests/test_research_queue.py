"""Offline regression tests for persistent private laptop research jobs.

Never contact market providers or send strategy output to GitHub workflows.
Every price series here is independently synthetic and contains no owner data.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from fastapi import HTTPException

from backend import portfolio_research, research_queue, main
from backend.main import app

CLIENT=TestClient(app)
START=datetime(2021,1,4,tzinfo=timezone.utc)
ASSETS=["spy","ief","gld"]


@pytest.fixture
def workspace(tmp_path,monkeypatch):
    monkeypatch.setattr(research_queue,"DB_PATH",tmp_path/"private_jobs.sqlite3")
    monkeypatch.setattr(portfolio_research,"DB_PATH",tmp_path/"private_models.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    monkeypatch.setattr(main,"PUBLIC_DEMO",False)
    def synthetic(asset,window):
        assert window=="5Y"
        prices=[]
        base=100.+ASSETS.index(asset)*30
        for i in range(510):
            day=START+timedelta(days=i)
            if day.weekday()>4:continue
            close=base*(1.0004+.001*math.sin(i/(8+ASSETS.index(asset))))
            candle={"time":int(day.timestamp()),"open":base,
                    "high":max(base,close)*1.002,
                    "low":min(base,close)*.998,
                    "close":close,"volume":15000}
            prices.append(candle)
            base=close
        # Need at least 450 *common market sessions*. 510 calendar days
        # is too short; add 400 more daily calendar periods.
        for i in range(510,790):
            day=START+timedelta(days=i)
            if day.weekday()>4:continue
            close=base*(1.0004+.001*math.sin(i/(8+ASSETS.index(asset))))
            prices.append({"time":int(day.timestamp()),"open":base,
                         "high":max(base,close)*1.002,
                         "low":min(base,close)*.998,
                         "close":close,"volume":15000})
            base=close
        return {"bars":prices,"source":"offline synthetic","is_demo":False}
    monkeypatch.setattr(portfolio_research,"history",synthetic)
    return tmp_path


def test_queue_survives_browser_lifecycle_and_worker_completes(workspace):
    response=CLIENT.post("/api/live/research/portfolio/jobs",
                         json={"symbols":ASSETS,"max_drawdown_pct":50})
    assert response.status_code==202,response.text
    job=response.json()
    assert job["status"]=="queued"
    assert job["result_run_id"] is None
    assert response.headers.get("cache-control") is None or response.headers["cache-control"]=="no-store"
    assert research_queue.DB_PATH.exists()
    # No page or API callback is needed to run the research after it queues.
    outcome=research_queue.process_one()
    assert outcome["status"]=="completed",outcome["error_code"]
    assert outcome["progress"]==100
    assert outcome["result_run_id"]==job["id"]
    detail=CLIENT.get("/api/live/research/portfolio/jobs/"+job["id"]).json()
    assert detail["status"]=="completed"
    study=CLIENT.get("/api/live/research/portfolio/runs/"+job["id"])
    assert study.status_code==200
    assert len(study.json()["candidates"])==len(portfolio_research.MODELS)
    assert research_queue.process_one() is None


def test_cancel_queued_job_remains_cancelled_without_running(workspace):
    job=research_queue.enqueue(ASSETS)
    assert research_queue.cancel(job["id"])["status"]=="cancelled"
    assert research_queue.process_one() is None
    assert not portfolio_research.DB_PATH.exists()
    assert research_queue.get_job(job["id"])["status"]=="cancelled"


def test_running_cancellation_cooperatively_stops_before_model_write(workspace,monkeypatch):
    job=research_queue.enqueue(ASSETS)
    original=portfolio_research.history
    def abort_on_first_market(symbol,window):
        research_queue.cancel(job["id"])
        return original(symbol,window)
    monkeypatch.setattr(portfolio_research,"history",abort_on_first_market)
    outcome=research_queue.process_one()
    assert outcome["status"]=="cancelled"
    assert portfolio_research.list_runs()==[]


def test_completed_result_is_linked_after_worker_restart(workspace,monkeypatch):
    job=research_queue.enqueue(ASSETS)
    original=portfolio_research.compare
    def simulate_crash_after_save(*args,**kwargs):
        original(*args,**kwargs)
        raise SystemExit("forced synthetic interruption after persistence")
    monkeypatch.setattr(portfolio_research,"compare",simulate_crash_after_save)
    with pytest.raises(SystemExit):
        research_queue.process_one()
    assert research_queue.get_job(job["id"])["status"]=="running"
    assert portfolio_research.load_run(job["id"])
    with research_queue._connect() as conn:
        conn.execute("UPDATE research_jobs SET updated_at='2020-01-01T00:00:00+00:00' WHERE id=?",(job["id"],))
    monkeypatch.setattr(portfolio_research,"compare",lambda *a,**kw:
                        pytest.fail("Should not rerun saved research"))
    outcome=research_queue.process_one()
    assert outcome["status"]=="completed"
    assert outcome["result_run_id"]==job["id"]


def test_failed_job_has_no_raw_provider_errors_or_credentials(workspace,monkeypatch):
    def secrets_in_exception(_symbol,_window):
        raise RuntimeError("https://secret-webhook.invalid/token?password=synthetic-secret")
    monkeypatch.setattr(portfolio_research,"history",secrets_in_exception)
    job=research_queue.enqueue(ASSETS)
    end=research_queue.process_one()
    assert end["status"]=="failed"
    assert end["error_code"]=="RuntimeError"
    assert "secret" not in str(end)
    assert "webhook" not in str(research_queue.list_jobs())
    assert end["result_run_id"] is None


def test_queue_bounded_and_duplicate_symbols_are_rejected(workspace):
    with pytest.raises(HTTPException) as err:
        research_queue.enqueue(["spy","spy"])
    assert err.value.status_code==422
    for _ in range(research_queue.MAX_PENDING):
        research_queue.enqueue(ASSETS)
    with pytest.raises(HTTPException) as err:
        research_queue.enqueue(ASSETS)
    assert err.value.status_code==429
    assert len(research_queue.list_jobs())==research_queue.MAX_PENDING


def test_demo_mode_rejects_web_research_queue_before_db_access(workspace,monkeypatch):
    monkeypatch.setattr(main,"PUBLIC_DEMO",True)
    for method,path in (
        ("get","/api/live/research/portfolio/jobs"),
        ("post","/api/live/research/portfolio/jobs"),
        ("get","/api/live/research/portfolio/jobs/notfound"),
        ("post","/api/live/research/portfolio/jobs/notfound/cancel"),
    ):
        if method=="post" and path.endswith("/jobs"):
            rsp=CLIENT.post(path,json={"symbols":ASSETS})
        elif method=="post":
            rsp=CLIENT.post(path)
        else:
            rsp=CLIENT.get(path)
        assert rsp.status_code==403
    assert not research_queue.DB_PATH.exists()


def test_no_queued_work_does_not_create_research_result_database(workspace):
    assert research_queue.process_one() is None
    assert not portfolio_research.DB_PATH.exists()
