"""Offline, synthetic tests for long-range GDELT GKG 1.0 daily history.

No real news data, provider requests, personal positions or selected
strategy details are used in CI.
"""
from __future__ import annotations
from datetime import date,datetime,timedelta,timezone
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from backend import historical_news as older
from backend import news_sentiment as recent
from backend.main import app


def gkg_row(day,org,count=2,tone="-3.2",source="test.invalid"):
    return "\t".join([
        day.strftime("%Y%m%d"),str(count),"","STOCK_MARKET","","",
        org,tone+",2,5,4,10,8","",source,"https://example.invalid/test"])


def zipped(day,rows):
    stream=BytesIO()
    with ZipFile(stream,"w",ZIP_DEFLATED) as z:
        z.writestr(day.strftime("%Y%m%d")+".gkg.csv",
                   "\n".join(rows)+"\n")
    stream.seek(0)
    return stream


@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(older,"DB_PATH",tmp_path/"historical.sqlite3")
    monkeypatch.setattr(recent,"DB_PATH",tmp_path/"live_headlines.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    return tmp_path


def test_daily_gkg_nameset_tone_uses_real_document_counts_not_fake_headlines(isolated):
    day=date(2020,1,3)
    rows=[
        gkg_row(day,"nvidia corporation;apple",count=4,tone="-6.0"),
        gkg_row(day,"Nvidia",count=2,tone="3.0"),
        gkg_row(day,"Tesla Motors",count=3,tone="5.0"),
        gkg_row(day,"unrelated organization",count=500,tone="90"),
    ]
    count,tone=older.parse_daily_zip(zipped(day,rows),day,["nvda","tsla"])
    assert count==4
    assert tone["nvda"]["namesets"]==2
    assert tone["nvda"]["mentions"]==6
    assert tone["nvda"]["raw_tone"]==pytest.approx(-3.)
    assert tone["nvda"]["score"]==pytest.approx(-.3)
    assert tone["tsla"]["raw_tone"]==pytest.approx(5.)
    assert tone["tsla"]["score"]==pytest.approx(.5)
    assert recent.scores_at(["nvda"],int(datetime(2020,1,5,tzinfo=timezone.utc).timestamp()))["nvda"]["score"] is None


def test_empty_entity_day_stays_covered_but_not_neutral(isolated):
    day=date(2019,6,7)
    count,tone=older.parse_daily_zip(zipped(day,[gkg_row(day,"unknown company",2,".1")]),
                                     day,["nvda"])
    assert count==1
    assert tone["nvda"]["score"] is None


def test_backfill_queue_creates_durable_resumable_daily_coverage(isolated):
    days=[]
    def fetcher(day,missing):
        days.append(day)
        metrics={s:{"score":.42,"raw_tone":4.2,
                    "namesets":3,"mentions":9} for s in missing}
        return "https://data.gdeltproject.org/gkg/"+day.strftime("%Y%m%d")+".gkg.csv.zip",42,metrics
    a=older.enqueue(["nvda","tsla"],"2020-01-02","2020-01-03")
    assert a["status"]=="queued"
    assert older.enqueue(["nvda","tsla"],"2020-01-02","2020-01-03")["id"]==a["id"]
    first=older.process_one(fetcher=fetcher)
    assert first["status"]=="running" and first["progress"]==50.
    second=older.process_one(fetcher=fetcher)
    assert second["status"]=="completed" and second["progress"]==100.
    assert days==[date(2020,1,2),date(2020,1,3)]
    reports=older.history(["nvda","tsla"],"2020-01-02","2020-01-03")
    assert len(reports["daily"])==4
    assert reports["live_eligible"] is False
    assert reports["coverage_days_by_symbol"]=={"nvda":2,"tsla":2}
    assert older.process_one(fetcher=fetcher) is None
    # A brand-new overlapping job is served from durable coverage, without
    # repeatedly downloading historical GKG ZIP files.
    overlap=older.enqueue(["nvda"],"2020-01-03","2020-01-03")
    out=older.process_one(fetcher=lambda d,s: (_ for _ in ()).throw(AssertionError("duplicate download")))
    assert out["status"]=="completed"
    assert overlap["processed_days"]==0


def test_conservative_historical_archive_time_gate(isolated):
    day=date(2018,3,9)
    old_news_time=older._archive_ready(day)
    assert older.historical_score_at("nvda",old_news_time+900) is None
    job=older.enqueue(["nvda"],"2018-03-09","2018-03-09")
    older.process_one(fetcher=lambda d,s:(
        "https://data.gdeltproject.org/gkg/20180309.gkg.csv.zip",12,
        {"nvda":{"score":-.5,"raw_tone":-5.,"namesets":2,"mentions":3}}))
    assert older.historical_score_at("nvda",old_news_time-1) is None
    assert older.historical_score_at("nvda",old_news_time)==-.5
    assert recent.scores_at(["nvda"],old_news_time+900)["nvda"]["score"] is None


def test_backfill_rejects_outside_range_or_ambiguous_proxy(isolated):
    for symbols,a,b in [
        (["spy"],"2020-01-01","2020-01-03"),
        (["nvda"],"2010-01-01","2010-01-03"),
        (["nvda"],"2020-01-01","2020-03-01"),
        (["nvda"],"2029-01-01","2029-01-03"),
        (["nvda","nvda"],"2020-01-01","2020-01-03"),
    ]:
        with pytest.raises(HTTPException) as exc:
            older.enqueue(symbols,a,b)
        assert exc.value.status_code==422


def test_failed_provider_does_not_create_fake_coverage_and_can_retry(isolated):
    job=older.enqueue(["nvda"],"2016-05-01","2016-05-01")
    def broken(day,missing):
        raise ValueError("Malformed historical provider ZIP")
    failed=older.process_one(fetcher=broken)
    assert failed["status"]=="failed"
    assert failed["processed_days"]==0
    assert older.history(["nvda"],"2016-05-01","2016-05-01")["daily"]==[]
    recovered=older.enqueue(["nvda"],"2016-05-01","2016-05-01")
    assert recovered["id"]!=job["id"]
    result=older.process_one(fetcher=lambda d,s:(
        "https://data.gdeltproject.org/gkg/20160501.gkg.csv.zip",1,
        {"nvda":{"score":None,"raw_tone":None,"namesets":0,"mentions":0}}))
    assert result["status"]=="completed"
    rows=older.history(["nvda"],"2016-05-01","2016-05-01")["daily"]
    assert rows[0]["status"]=="no_entity_match" and rows[0]["score"] is None


def test_cancel_before_worker_is_respected(isolated):
    job=older.enqueue(["nvda"],"2020-01-01","2020-01-01")
    assert older.cancel(job["id"])["status"]=="cancelled"
    assert older.process_one(fetcher=lambda *_: (_ for _ in ()).throw(Exception())) is None


def test_private_routes_use_background_jobs_not_network_requests(isolated,monkeypatch):
    client=TestClient(app)
    created=client.post("/api/live/research/news/history/jobs",json={
        "symbols":["nvda"],"start_date":"2020-04-01","end_date":"2020-04-02"})
    assert created.status_code==202
    job=created.json()
    got=client.get("/api/live/research/news/history/jobs/"+job["id"])
    assert got.status_code==200 and got.json()["total_days"]==2
    listed=client.get("/api/live/research/news/history/jobs")
    assert listed.status_code==200 and listed.json()[0]["id"]==job["id"]
    fetched=client.get("/api/live/research/news/history?symbols=nvda&start_date=2020-04-01&end_date=2020-04-02")
    assert fetched.status_code==200 and fetched.json()["daily"]==[]
    assert client.post("/api/live/research/news/history/jobs/"+job["id"]+"/cancel").json()["status"]=="cancelled"
    monkeypatch.setattr("backend.main.PUBLIC_DEMO",True)
    assert client.get("/api/live/research/news/history/jobs").status_code==403
    assert client.post("/api/live/research/news/history/jobs",json={
        "symbols":["nvda"],"start_date":"2020-04-01","end_date":"2020-04-02"}).status_code==403
