"""Independent synthetic tests for broker-aware research, currency and fills."""
from __future__ import annotations

from datetime import datetime, time
from math import isclose
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException

from backend import broker_execution as broker
from backend import paper_forward as paper
from backend.tests.test_paper_forward import DAYS, asof, provider, paper_job

NY = ZoneInfo("America/New_York")


@pytest.fixture
def local(tmp_path,monkeypatch):
    monkeypatch.setattr(paper,"DB_PATH",tmp_path/"isolated_broker_paper.sqlite3")
    monkeypatch.setattr(paper.walkforward_queue,"get_job",lambda _:paper_job())
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)


def fx_loader(count, *, unavailable=False):
    market=provider(count)
    def load(symbol,period):
        if symbol!="usdcad":return market(symbol,period)
        bars=[]
        for i,day in enumerate(DAYS[:count]):
            stamp=datetime.combine(day,time(0),NY)
            fx=1.2+i*.0004
            bars.append({"time":int(stamp.timestamp()),"open":fx,
                         "high":fx*1.002,"low":fx*.998,"close":fx})
        return {"bars":bars,"source":"independently synthetic FX",
                "is_demo":False,"offline_cache":unavailable}
    return load


def profile(**kwargs):
    return broker.normalize({"broker":"wealthsimple","account_type":"cash",**kwargs})


def test_broker_pricing_profiles_and_cash_short_constraints():
    cash=profile()
    assert broker.order_fee_usd(cash,120,9000)==0
    assert broker.fx_commission_usd(cash,9999,1.4)==pytest.approx(9999/1.4*.015)
    assert broker.fx_commission_usd(cash,10000,1.4)==pytest.approx(10000/1.4*.01)
    assert broker.fx_commission_usd(cash,100000,1.4)==0
    margin=profile(account_type="margin")
    assert broker.margin_rate_pct(margin,5000,1.4)==8.0
    assert broker.margin_rate_pct(margin,30000,1.4)==7.9
    ib=broker.normalize({"broker":"ibkr"})
    assert broker.order_fee_usd(ib,100,8000)==pytest.approx(.35)
    assert broker.order_fee_usd(ib,500,20000)==pytest.approx(1.75)
    assert broker.fx_commission_usd(ib,10000,1.4)==2
    with pytest.raises(ValueError,match="Short shares"):
        broker.check_model(cash,"long_short_momentum")
    with pytest.raises(ValueError,match="Short"):
        broker.check_model(margin,"long_short_momentum")
    with pytest.raises(ValueError,match="unverified"):
        broker.check_model(ib,"market_neutral")
    broker.check_model(broker.normalize({
        "broker":"ibkr","borrow_policy":"assume_available_research"}),"market_neutral")
    with pytest.raises(ValueError):
        broker.normalize({"broker":"wealthsimple",
                          "borrow_policy":"assume_available_research"})
    with pytest.raises(ValueError):
        broker.normalize({"broker":"ibkr","margin_rate_pct":float("nan")})


def test_cad_funding_fx_is_charged_once_and_revalued_without_future_quote(local):
    execution={"broker":"wealthsimple","account_type":"cash",
               "capital_currency":"CAD","fill_timing":"next_open"}
    started=paper.create("cad-one",capital=20000,now=asof(510),
                         loader=fx_loader(510),execution=execution)
    spot=1.2+508*.0004
    nominal=20000/spot
    fee=nominal*.01
    assert started["initial_capital"]==pytest.approx(nominal)
    assert started["fx_rate"]==pytest.approx(spot)
    assert started["cash"]==pytest.approx(nominal-fee,abs=.01)
    assert started["equity_cad"]==pytest.approx(19800,abs=.01)
    assert started["paper_pnl_cad"]==pytest.approx(-200,abs=.01)
    assert paper.get_study(started["id"])["marks"][0]["value_cad"]==pytest.approx(19800)
    advanced=paper.process_one(started["id"],now=asof(511),loader=fx_loader(511))
    assert advanced["observed_sessions"]==1
    assert advanced["fx_rate"]==pytest.approx(1.2+509*.0004)
    assert advanced["current_drawdown_cad_pct"] is not None
    assert advanced["transaction_fees_paid"]==0
    same=paper.process_one(started["id"],now=asof(511),loader=fx_loader(511))
    assert same["observed_sessions"]==1
    assert len(paper.get_study(started["id"])["marks"])==2


def test_independent_broker_scenarios_from_one_frozen_selection(local):
    ws=paper.create("same-run",now=asof(510),loader=provider(510),
                    execution={"broker":"wealthsimple","account_type":"cash"})
    ib=paper.create("same-run",now=asof(510),loader=provider(510),
                    execution={"broker":"ibkr","account_type":"margin"})
    assert ws["id"]!=ib["id"]
    ws_one=paper.process_one(ws["id"],now=asof(511),loader=provider(511))
    ib_one=paper.process_one(ib["id"],now=asof(511),loader=provider(511))
    assert ws_one["transaction_fees_paid"]==0
    assert ib_one["transaction_fees_paid"]>0
    assert ws_one["equity"]>ib_one["equity"]
    repeat=paper.create("same-run",now=asof(510),loader=provider(510),
                        execution={"broker":"ibkr","account_type":"margin"})
    assert repeat["id"]==ib["id"]


def test_close_scenario_differs_from_open_fill_and_is_paper_only(local):
    start=asof(510)
    open_case=paper.create("open-case",now=start,loader=provider(510),
                           execution={"broker":"ibkr","fill_timing":"next_open"})
    close_case=paper.create("close-case",now=start,loader=provider(510),
                            execution={"broker":"ibkr","fill_timing":"next_close"})
    paper.process_one(open_case["id"],now=asof(511),loader=provider(511))
    paper.process_one(close_case["id"],now=asof(511),loader=provider(511))
    a=paper.get_study(open_case["id"])
    b=paper.get_study(close_case["id"])
    assert a["fills"] and b["fills"]
    assert a["fills"][0]["price"]!=b["fills"][0]["price"]
    assert a["research_only"] and b["simulated_fills_only"]


def test_cad_fx_data_must_be_confirmed_at_activation_and_on_update(local):
    execution={"broker":"wealthsimple","capital_currency":"CAD"}
    with pytest.raises(HTTPException) as e:
        paper.create("fx-block",now=asof(510),
                     loader=fx_loader(510,unavailable=True),execution=execution)
    assert e.value.status_code==422
    created=paper.create("fx-recover",now=asof(510),
                         loader=fx_loader(510),execution=execution)
    blocked=paper.process_one(created["id"],now=asof(511),
                              loader=fx_loader(511,unavailable=True))
    assert blocked["observed_sessions"]==0
    assert blocked["last_error"]


def test_usd_funded_wealthsimple_margin_uses_real_fx_for_debt_tiers(local):
    execution={"broker":"wealthsimple","account_type":"margin",
               "capital_currency":"USD"}
    started=paper.create("usd-margin",now=asof(510),
                         loader=fx_loader(510),execution=execution)
    assert started["capital_currency"]=="USD"
    assert started["fx_rate"]==pytest.approx(1.2+508*.0004)
    assert started["initial_capital"]==100000
    assert started["fx_conversion_fee_usd"]==0
    assert started["paper_pnl_cad"] is None
    assert started["current_drawdown_cad_pct"] is None
    updated=paper.process_one(started["id"],now=asof(511),loader=fx_loader(511))
    assert updated["observed_sessions"]==1
    assert updated["fx_rate"]==pytest.approx(1.2+509*.0004)


def test_activation_after_open_cannot_fill_at_earlier_auction(local):
    assert DAYS[508].weekday()==3  # independently synthetic Thursday
    started=paper.create("after-open",now=asof(509),loader=provider(509),
                         execution={"broker":"ibkr","fill_timing":"next_open"})
    first=paper.process_one(started["id"],now=asof(510),loader=provider(510))
    assert first["observed_sessions"]==1
    assert first["pending_execution"]
    assert paper.get_study(started["id"])["fills"]==[]
    second=paper.process_one(started["id"],now=asof(511),loader=provider(511))
    assert second["observed_sessions"]==2
    assert paper.get_study(started["id"])["fills"]

    close_study=paper.create("after-open-close",now=asof(509),loader=provider(509),
                             execution={"broker":"ibkr","fill_timing":"next_close"})
    paper.process_one(close_study["id"],now=asof(510),loader=provider(510))
    assert paper.get_study(close_study["id"])["fills"]


def test_borrow_capability_is_not_approval(local,monkeypatch):
    job=paper_job()
    job["result"]["final_audit"]["selected"]["model"]="long_short_momentum"
    job["result"]["symbols"]=["spy","qqq","pltr","nvda"]
    monkeypatch.setattr(paper.walkforward_queue,"get_job",lambda _:job)
    with pytest.raises(HTTPException):
        paper.create("ws-short",now=asof(510),loader=provider(510),
                     execution={"broker":"wealthsimple","account_type":"margin"})
    with pytest.raises(HTTPException):
        paper.create("ib-short-blocked",now=asof(510),loader=provider(510),
                     execution={"broker":"ibkr"})
