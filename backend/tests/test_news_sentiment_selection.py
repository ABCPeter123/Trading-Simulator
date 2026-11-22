"""Synthetic-only coverage for the free news collector and practical winner.

Never fetch real URLs, read owner news, or publish owner strategy records.
"""
from datetime import datetime, timedelta, timezone
import copy
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from backend import news_sentiment as news
from backend import practical_selection as practical
from backend.main import app

BASE=datetime(2026,11,21,15,tzinfo=timezone.utc)
NOW=int(BASE.timestamp())


@pytest.fixture
def archive(tmp_path,monkeypatch):
    monkeypatch.setattr(news,"DB_PATH",tmp_path/"private_news.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    return tmp_path


class DummyReply:
    def raise_for_status(self):pass
    def json(self):
        return {"articles":[
            {"title":"Nvidia beats estimates and raises guidance after strong demand",
             "url":"https://example.net/a","seendate":"20261120T140000Z"},
            {"title":"Nvidia cuts guidance due to weak demand",
             "url":"https://example.net/b","seendate":"20261120T130000Z"},
            {"title":"Nvidia beats estimates and raises guidance after strong demand",
             "url":"https://example.net/a","seendate":"20261120T140000Z"}]}


class DummyClient:
    def __init__(self):self.calls=[]
    def get(self,url,params):
        self.calls.append((url,params))
        assert url==news.BASE_URL and params["mode"]=="artlist"
        return DummyReply()


def test_gdelt_archive_has_no_lookahead_even_when_article_was_published_yesterday(archive):
    client=DummyClient()
    out=news.refresh(["nvda"],client=client,now=BASE)
    assert out["key_required"] is False
    assert out["results"][0]["new_articles"]==2
    assert len(client.calls)==1
    # No "prior" signal from GDELT yesterday, before this machine archived it.
    before=news.scores_at(["nvda"],NOW-60)
    assert before["nvda"]["score"] is None
    later=news.scores_at(["nvda"],NOW+60)
    assert later["nvda"]["scored_headlines"]==2
    assert later["nvda"]["score"] is not None
    snapshot=news.snapshot(["nvda"],now=BASE+timedelta(minutes=1))
    assert all(headline["first_observed_utc"]==NOW for headline in
               snapshot["instruments"]["nvda"]["headlines"])
    # Re-running within a quarter hour serves local cache; no paid or repeat request.
    again=news.refresh(["nvda"],client=client,now=BASE+timedelta(minutes=4))
    assert again["results"][0]["status"]=="cached"
    assert len(client.calls)==1


def test_sentiment_direction_and_risk_tilt_are_conservative():
    assert news.sentiment("Company beats estimates, raises guidance")>0
    assert news.sentiment("Company cuts guidance after earnings miss")<0
    assert news.sentiment("Company declares quarterly earnings date")==0
    prior={"nvda":.40,"spy":.25,"ief":.20}
    scores={"nvda":{"score":-.85},"spy":{"score":+.9},
            "ief":{"score":None}}
    new=news.risk_tilt(prior,scores)
    assert 0<new["nvda"]<prior["nvda"]
    assert new["spy"]==prior["spy"]
    assert new["ief"]==prior["ief"]
    assert sum(new.values())<=sum(prior.values())


def test_private_api_and_demo_guard(archive):
    client=TestClient(app)
    req=client.get("/api/live/research/news/sentiment?symbols=nvda,spy")
    assert req.status_code==200
    assert req.json()["scores"]["nvda"]["score"] is None
    invalid=client.post("/api/live/research/news/refresh",
        json={"symbols":["invalid-no-such-ticker"]})
    assert invalid.status_code==422
    # Public demo has no access to private news sources or archive.
    import os
    original=os.environ.get("TRADING_SIM_PUBLIC_DEMO")
    os.environ["TRADING_SIM_PUBLIC_DEMO"]="1"
    try:
        assert client.get("/api/live/research/news/sentiment?symbols=nvda").status_code==403
        assert client.post("/api/live/research/news/refresh",
                           json={"symbols":["nvda"]}).status_code==403
    finally:
        if original is None:os.environ.pop("TRADING_SIM_PUBLIC_DEMO",None)
        else:os.environ["TRADING_SIM_PUBLIC_DEMO"]=original


def selection_candidate(model="trend_filter", sharpe=1.1, dd=-12., symbols=None):
    symbols=symbols or ["spy","ief","gld"]
    return {"model":model,"basket_type":"synthetic","symbols":symbols,
            "sleeves":None,"validation":{"return_pct":16.,
                "max_drawdown_pct":dd,"turnover_pct":90.},
            "validation_objectives":{"excess_sharpe":sharpe},
            "validation_execution_stress":{"return_pct":12.,
                                             "max_drawdown_pct":dd-2},
            "validation_stability":{"positive_windows":3,"window_count":3},
            "validation_benchmark_advantage":{"excess_return_points":4,
                "beats_same_basket_return":True,
                "beats_same_basket_risk_adjusted":True},
            "_metadata":{s:{"currency":"USD"} for s in symbols},
            "_validation_executions":[
                {"symbol":"spy","side":"buy","quantity":100,"price":100.,"fee":0.},
                {"symbol":"spy","side":"sell","quantity":100,"price":110.,"fee":0.}],
            "train":{}}


def test_selects_only_one_best_executable_sharpe_drawdown_and_tax():
    simple=selection_candidate(sharpe=1.4,dd=-12.)
    high_vol=selection_candidate(sharpe=1.6,dd=-29.)
    short=selection_candidate(model="market_neutral",sharpe=6.,dd=-1.)
    leveraged=selection_candidate(symbols=["tqqq","spy"],sharpe=7.,dd=-1.)
    chosen,report=practical.choose([high_vol,short,leveraged,simple],
        max_drawdown_pct=30.,tax_rate_pct=25.,require_delay_stress=True)
    assert chosen is simple
    assert report["eligible"]==2
    assert report["selected"]["estimated_tax_reserve_usd"]==250.
    assert report["selected"]["demonstrated_edge"]
    assert report["selected"]["recommendation_status"]=="research_candidate_requires_paper_forward"
    no,details=practical.choose([short,leveraged],max_drawdown_pct=30.)
    assert no is None
    assert details["reason"]=="no_cash_executable_validation_candidate"


def test_realized_tax_proxy_is_only_assumption_and_has_no_future_data():
    base=selection_candidate()
    no_tax=practical.evaluate(base,tax_rate_pct=0)
    taxable=practical.evaluate(base,tax_rate_pct=35)
    assert no_tax["estimated_tax_reserve_usd"]==0.
    assert taxable["estimated_tax_reserve_usd"]==350.
    assert taxable["score"]<no_tax["score"]
    assert taxable["tax_method"].startswith("Conservative")
    future=copy.deepcopy(base)
    future["_sealed_test"]=dict(sharpe=250.,return_pct=999.)
    assert practical.evaluate(future)==practical.evaluate(base)
