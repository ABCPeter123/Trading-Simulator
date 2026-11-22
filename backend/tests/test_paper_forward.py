"""Purely synthetic and isolated tests for forward-paper portfolio observations."""
from __future__ import annotations

from datetime import datetime, timedelta, time
from math import sin
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import paper_forward as paper
from backend.main import app

NY = ZoneInfo("America/New_York")
START = datetime(2022, 1, 3, tzinfo=NY).date()
DAYS = [START + timedelta(days=i) for i in range(1000)
        if (START + timedelta(days=i)).weekday() < 5]
SYMBOLS = ["spy", "qqq", "ief"]


def asof(count):
    return datetime.combine(DAYS[count - 1] + timedelta(days=1), time(13), NY)


def provider(count, *, shock=False, off=False, missing=False):
    def load(symbol, period):
        assert symbol in SYMBOLS and period == "5Y"
        rows = []
        for i, day in enumerate(DAYS[:count]):
            if missing and symbol == "qqq" and i == count - 2:
                continue
            px = (85 + 12 * SYMBOLS.index(symbol)) * (1.00012 ** i) * (1 + .01 * sin(i / 29))
            opening, closing = px, px * (1 + .0006 * sin(i))
            if shock and i >= 510:
                closing *= .5
            stamp = datetime.combine(day, time(0), NY)
            rows.append({"time":int(stamp.timestamp()),"open":opening,
                         "high":max(opening, closing)*1.02,
                         "low":min(opening, closing)*.98,
                         "close":closing,"volume":10000 + i})
        return {"bars":rows,"source":"independent synthetic fixture",
                "is_demo":False,"offline_cache":off}
    return load


def paper_job(delay=1):
    config={"model":"equal_weight","max_position_pct":40.,"delay_sessions":delay,
            "target_investment_pct":95.,"equity_class_cap_pct":70.,
            "redistribute_excess":False}
    return {"status":"completed","result":{
        "status":"completed","symbols":SYMBOLS,
        "targets":{"risk_free_pct":3.},
        "final_audit":{"selected":config,
            "objectives":{"cagr_pct":12.,"excess_sharpe":1.}}}}


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(paper,"DB_PATH",tmp_path/"isolated_paper.sqlite3")
    monkeypatch.setattr(paper.walkforward_queue,"get_job",lambda uid:paper_job())
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    return tmp_path


def test_new_session_only_fill_and_idempotent_restart(isolated):
    created=paper.create("synthetic-1",now=asof(510),loader=provider(510))
    assert created["observed_sessions"]==0
    assert created["pending_execution"] is True
    initial=paper.get_study(created["id"])
    assert len(initial["marks"])==1 and initial["fills"]==[]
    assert initial["starting_session"]==DAYS[509].isoformat()
    tick=paper.process_one(created["id"],now=asof(511),loader=provider(511))
    assert tick["observed_sessions"]==1
    assert tick["last_error"] is None
    studied=paper.get_study(created["id"])
    assert studied["fills"] and len(studied["marks"])==2
    assert studied["simulated_fills_only"] is True
    assert studied["drift"]["status"]=="insufficient_forward_sessions"
    assert studied["statistics"]["cagr_pct"] is None
    assert studied["statistics"]["excess_sharpe"] is None
    assert studied["marks"][-1]["session"]==DAYS[510].isoformat()
    repeated=paper.process_one(created["id"],now=asof(511),loader=provider(511))
    assert repeated["observed_sessions"]==1
    assert len(paper.get_study(created["id"])["fills"])==len(studied["fills"])
    assert paper.list_studies()[0]["id"]==created["id"]
    assert not (isolated/"live_machine.sqlite3").exists()


def test_frozen_forward_benchmark_is_exact_session_and_restart_safe(isolated):
    created=paper.create("synthetic-benchmark",now=asof(510),loader=provider(510))
    assert created["frozen_strategy_fingerprint"]
    fingerprint=created["frozen_strategy_fingerprint"]
    benchmark=created["forward_benchmark"]
    assert benchmark["status"]=="available"
    assert benchmark["benchmark_used_to_select_strategy"] is False
    assert benchmark["return_pct"]==0.
    baseline=paper.get_study(created["id"])
    assert baseline["marks"][0]["benchmark_value"]==baseline["marks"][0]["value"]
    paper.process_one(created["id"],now=asof(511),loader=provider(511))
    observed=paper.get_study(created["id"])
    assert observed["frozen_strategy_fingerprint"]==fingerprint
    assert observed["forward_benchmark"]["observed_sessions"]==1
    assert len(observed["marks"])==2
    assert observed["marks"][-1]["benchmark_value"]>0
    assert observed["forward_benchmark"]["value_usd"]==round(
        observed["marks"][-1]["benchmark_value"],2)
    prior_value=observed["marks"][-1]["benchmark_value"]
    paper.process_one(created["id"],now=asof(511),loader=provider(511))
    again=paper.get_study(created["id"])
    assert again["marks"][-1]["benchmark_value"]==prior_value
    assert len(again["marks"])==2


def test_pre_upgrade_forward_study_does_not_backfill_fake_reference(isolated):
    import json
    from contextlib import closing
    created=paper.create("synthetic-legacy",now=asof(510),loader=provider(510))
    with closing(paper._db()) as c:
        state=json.loads(c.execute(
            "SELECT state FROM paper_studies WHERE id=?",
            (created["id"],)).fetchone()[0])
        state.pop("forward_benchmark")
        state.pop("frozen_strategy_fingerprint")
        c.execute("UPDATE paper_studies SET state=? WHERE id=?",
                  (paper._dump(state),created["id"]))
        c.execute("UPDATE paper_marks SET benchmark_value=NULL WHERE study_id=?",
                  (created["id"],))
    existing=paper.get_study(created["id"])
    assert existing["forward_benchmark"]["status"]=="not_recorded"
    assert existing["frozen_strategy_fingerprint"] is None
    paper.process_one(created["id"],now=asof(511),loader=provider(511))
    later=paper.get_study(created["id"])
    assert all(mark["benchmark_value"] is None for mark in later["marks"])


def test_two_session_delay_is_not_a_same_day_fill(isolated,monkeypatch):
    monkeypatch.setattr(paper.walkforward_queue,"get_job",lambda uid:paper_job(2))
    created=paper.create("synthetic-2",now=asof(510),loader=provider(510))
    paper.process_one(created["id"],now=asof(511),loader=provider(511))
    assert paper.get_study(created["id"])["fills"]==[]
    paper.process_one(created["id"],now=asof(512),loader=provider(512))
    detail=paper.get_study(created["id"])
    assert detail["observed_sessions"]==2
    assert detail["fills"]
    assert {order["session"] for order in detail["fills"]}=={DAYS[511].isoformat()}


def test_bad_feed_blocks_and_subsequent_good_feed_recovers(isolated):
    created=paper.create("synthetic-3",now=asof(510),loader=provider(510))
    blocked=paper.process_one(created["id"],now=asof(511),loader=provider(511,off=True))
    assert blocked["observed_sessions"]==0 and blocked["last_error"]
    recovered=paper.process_one(created["id"],now=asof(511),loader=provider(511))
    assert recovered["observed_sessions"]==1 and recovered["last_error"] is None
    missing=paper.process_one(created["id"],now=asof(513),loader=provider(513,missing=True))
    assert missing["observed_sessions"]==1 and missing["last_error"]


def test_paper_drawdown_stop_and_new_study_after_pause(isolated):
    first=paper.create("synthetic-4",max_drawdown_pct=5.,
                       now=asof(510),loader=provider(510))
    marked=paper.process_one(first["id"],now=asof(511),
                             loader=provider(511,shock=True))
    assert marked["status"]=="paused"
    assert marked["observed_sessions"]==1
    assert marked["current_drawdown_pct"]<=-5
    with pytest.raises(HTTPException) as e:
        paper.change_status(first["id"],"active")
    assert e.value.status_code==409
    another=paper.create("synthetic-4",max_drawdown_pct=5.,
                         now=asof(512),loader=provider(512))
    assert another["id"]!=first["id"]
    assert another["starting_session"]==DAYS[511].isoformat()


def test_multiple_unobserved_sessions_stop_instead_of_backfilling(isolated):
    created=paper.create("synthetic-gap",now=asof(510),loader=provider(510))
    result=paper.process_one(created["id"],now=asof(512),loader=provider(512))
    assert result["status"]=="paused"
    assert result["observed_sessions"]==0
    assert result["last_error"]
    detail=paper.get_study(created["id"])
    assert len(detail["marks"])==1
    assert detail["fills"]==[]


def test_synthetic_short_sleeve_accumulates_borrow_costs(isolated,monkeypatch):
    monkeypatch.setitem(globals(),"SYMBOLS",["spy","qqq","pltr","nvda"])
    job=paper_job()
    job["result"]["final_audit"]["selected"]["model"]="long_short_momentum"
    monkeypatch.setattr(paper.walkforward_queue,"get_job",lambda uid:job)
    created=paper.create("synthetic-signed",now=asof(510),loader=provider(510))
    result=paper.process_one(created["id"],now=asof(511),loader=provider(511))
    detail=paper.get_study(created["id"])
    assert result["observed_sessions"]==1
    assert any(fill["action"]=="short_sell" for fill in detail["fills"])
    assert detail["financing_paid"]>0
    assert detail["gross_exposure_pct"]>0
    assert result["research_only"] and result["simulated_fills_only"]


def test_private_http_endpoints_and_demo_isolation(isolated,monkeypatch):
    monkeypatch.setattr(paper,"create",lambda job_id,**kw:{"source_job_id":job_id,"status":"active"})
    client=TestClient(app)
    ok=client.post("/api/live/research/paper-forward",
                   json={"job_id":"synthetic-5","capital":100000,"max_drawdown_pct":30})
    assert ok.status_code==201 and ok.json()["status"]=="active"
    monkeypatch.setattr("backend.main.PUBLIC_DEMO",True)
    denied=client.get("/api/live/research/paper-forward")
    assert denied.status_code==403
    denied_create=client.post("/api/live/research/paper-forward",
                   json={"job_id":"synthetic-5"})
    assert denied_create.status_code==403



def test_forward_paper_preserves_weekly_cadence_across_new_observed_sessions(isolated,monkeypatch):
    def job(_):
        source=paper_job()
        source["result"]["final_audit"]["selected"]["rebalance_sessions"]=5
        return source
    monkeypatch.setattr(paper.walkforward_queue,"get_job",job)
    created=paper.create("synthetic-weekly",now=asof(510),loader=provider(510))
    assert created["pending_execution"] is True
    for count in range(511,515):
        paper.process_one(created["id"],now=asof(count),loader=provider(count))
        assert paper.get_study(created["id"])["pending_execution"] is False
    paper.process_one(created["id"],now=asof(515),loader=provider(515))
    queued=paper.get_study(created["id"])
    assert queued["pending_execution"] is True
    assert queued["observed_sessions"]==5
    repeated=paper.process_one(created["id"],now=asof(515),loader=provider(515))
    assert repeated["observed_sessions"]==5
    assert repeated["pending_execution"] is True



def test_news_overlay_is_explicit_opt_in_and_frozen_per_forward_study(isolated,monkeypatch):
    import json
    from contextlib import closing
    monkeypatch.setattr(paper.news_sentiment,"scores_at",lambda names,at:{
        name:{"score":-.8} if name=="spy" else {"score":None} for name in names})
    usual=paper.create("synthetic-news",now=asof(510),loader=provider(510),
                       news_sentiment_overlay=False)
    news=paper.create("synthetic-news",now=asof(510),loader=provider(510),
                      news_sentiment_overlay=True)
    assert usual["id"]!=news["id"]
    assert usual["news_sentiment_overlay"] is False
    assert news["news_sentiment_overlay"] is True
    def pending(uid):
        with closing(paper._db()) as conn:
            return json.loads(conn.execute("SELECT state FROM paper_studies WHERE id=?",
                                           (uid,)).fetchone()[0])["pending"]["weights"]
    baseline=pending(usual["id"])
    tilted=pending(news["id"])
    assert tilted["spy"]==pytest.approx(baseline["spy"]*(1-.35*.8))
    assert tilted["ief"]==pytest.approx(baseline["ief"])
    assert sum(tilted.values())<=sum(baseline.values())
    # Existing forward allocations never change because the collector
    # receives later news: no retroactive study recalculation.
    monkeypatch.setattr(paper.news_sentiment,"scores_at",lambda names,at:{
        name:{"score":+.95} for name in names})
    assert pending(news["id"])==tilted


def test_news_overlay_validation_rejects_nonboolean(isolated):
    with pytest.raises(HTTPException) as exc:
        paper.create("invalid-news-mode",now=asof(510),loader=provider(510),
                     news_sentiment_overlay="yes")
    assert exc.value.status_code==422
