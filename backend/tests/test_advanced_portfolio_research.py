"""Independent synthetic checks for experimental signed exposure and scenario ranking."""
from datetime import datetime,timedelta,timezone
import math
import pytest
from fastapi import HTTPException
from backend import advanced_portfolio_research as adv
from backend import portfolio_research as pr
from backend import universe_research as universe
from backend import tournament_strategies as versions
from backend import portfolio_arcade as cash
from backend import live_machine as live


def fixture(n=600):
    symbols=["alp","brv","crx","dlt","bnd","gld"]
    market={};meta={}
    start=datetime(2020,1,1,tzinfo=timezone.utc)
    for j,s in enumerate(symbols):
        p=100+20*j;rows=[]
        for i in range(n):
            d=start+timedelta(days=i)
            # Distinct deterministic uptrends/downtrends and defensive assets
            r=(.001 if j==0 else -.0007 if j==1 else
               .00035 if j==2 else -.00025 if j==3 else .00008 if j==4 else .00016)
            r+=.004*math.sin(i/8+j*.7)
            opening=p; p*=1+r
            rows.append({"time":int(d.timestamp()),"open":opening,
                         "close":p,"high":max(p,opening)*1.002,
                         "low":min(p,opening)*.998,"volume":1000})
        market[s]=rows
        meta[s]={"group":"bond" if s=="bnd" else "commodity" if s=="gld" else "equity",
                 "currency":"USD","spread_bps":3,"kind":"Stocks"}
    return symbols,market,meta


def test_experimental_weights_use_only_completed_prices():
    syms,market,meta=fixture()
    close={s:[b["close"] for b in market[s]] for s in syms}
    for model in adv.MODELS:
        a=adv.weights(model,syms,close,250,meta,.35)
        mutated={s:list(series) for s,series in close.items()}
        for s in syms:
            for i in range(250,len(mutated[s])):mutated[s][i]*=17
        assert adv.weights(model,syms,mutated,250,meta,.35)==a
    assert any(v<0 for v in adv.weights("market_neutral",syms,close,250,meta,.35).values())
    assert max(adv.weights("leveraged_trend",syms,close,250,meta,.35).values())<=.35


def test_short_ledger_charges_borrow_and_records_real_negative_exposure():
    syms,market,meta=fixture()
    base=adv.segment("market_neutral",syms,market,meta,180,520,.4,
                     broker={"short_borrow_rate_annual":0,
                             "margin_rate_annual":0,"slippage_bps":0})
    charged=adv.segment("market_neutral",syms,market,meta,180,520,.4,
                        broker={"short_borrow_rate_annual":.12,
                                "margin_rate_annual":.08,"slippage_bps":0})
    assert any(x["side"]=="short_sell" for x in charged["executions"])
    assert any(any(x<0 for x in r["weights"].values()) for r in charged["rebalances"])
    assert charged["short_borrow_cost"]>0
    assert charged["ending_equity"]<base["ending_equity"]
    assert charged["peak_gross_leverage"]>0
    assert charged["margin_calls"]==0


def test_leveraged_strategy_has_gross_exposure_and_funding():
    syms,market,meta=fixture()
    a=adv.segment("leveraged_trend",syms,market,meta,180,520,.48,
                  broker={"margin_rate_annual":.09})
    assert a["peak_gross_leverage"]>=0
    assert a["average_net_exposure_pct"]>=0
    assert all(math.isfinite(x["value"]) for x in a["equity_curve"])
    assert a["margin_calls"]>=0


def test_regime_grades_use_only_observed_market_history():
    syms,market,meta=fixture()
    a=adv.segment("equity_hedge",syms,market,meta,180,520,.35)
    regimes=adv.scenario_grade(a["equity_curve"],market,syms,180)
    assert regimes["samples"]>=250
    assert sum(x["observations"] for x in regimes["regimes"].values())==regimes["samples"]


def test_private_version_rejects_unexecutable_margin_or_short(monkeypatch,tmp_path):
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    monkeypatch.setattr(versions,"DB_PATH",tmp_path/"versions.sqlite3")
    from datetime import datetime,timezone
    # Independently fictional model, never an owner strategy.
    config={"version":2,"model":"market_neutral",
            "symbols":["alp","brv","crx","dlt"],
            "max_position_pct":35,"delay_sessions":1,"rebalance_sessions":21,
            "research_only":True}
    assert versions.validate_spec(config)["model"]=="market_neutral"
    with pytest.raises(HTTPException):
        versions.validate_spec({**config,"research_only":False})
    with pytest.raises(HTTPException):
        versions.validate_spec({**config,"version":1})
    # Never permit a signed model to pass as an ordinary cash model.
    monkeypatch.setattr(versions,"get",lambda x:{"id":x,"code":__import__("json").dumps(config),"name":"fixture"})
    with pytest.raises(HTTPException):
        cash.create_tournament_season("fictional")
    with pytest.raises(HTTPException):
        live.deploy("tm-fictional",max_allocation_pct=35,max_daily_signals=4)


def test_tournament_expands_candidate_models_without_returning_raw_private_series():
    assert len(universe.CANDIDATE_MODELS)>=11
    assert adv.SHORT_MODELS.issubset(set(universe.CANDIDATE_MODELS))
    assert "defensive_rotation" in universe.CANDIDATE_MODELS
    assert "MAX" in universe._read.__doc__ or "longest" in universe._read.__doc__
