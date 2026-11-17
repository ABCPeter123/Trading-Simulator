"""Synthetic held-out strategy discovery tests: test data never selects models."""
import math
from datetime import datetime,timedelta,timezone

import pytest
from fastapi import HTTPException

from backend import research_optimizer as optimizer, strategy_library as library

@pytest.fixture
def dbs(tmp_path,monkeypatch):
    monkeypatch.setattr(optimizer,"DB_PATH",tmp_path/"research.sqlite3")
    monkeypatch.setattr(library,"DB_PATH",tmp_path/"strategies.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)

def synthetic(n=520,shock=False):
    start=datetime(2022,1,1,tzinfo=timezone.utc)
    bars=[]
    for i in range(n):
        baseline=100+math.sin(i/9)*8+math.sin(i/41)*4+i*.015
        if shock and i>=int(.8*n):
            baseline*=.5
        prev=baseline if not bars else bars[-1]["close"]
        bars.append({"time":int((start+timedelta(days=i)).timestamp()),
             "open":prev,"high":max(prev,baseline)*1.01,
             "low":min(prev,baseline)*.99,"close":baseline,"volume":10000})
    return {"bars":bars,"source":"synthetic test data"}

def test_selection_never_reads_held_out_test(dbs):
    a=optimizer.optimize("spy",max_drawdown_pct=30,allocation_pct=20,data=synthetic())
    b=optimizer.optimize("spy",max_drawdown_pct=30,allocation_pct=20,data=synthetic(shock=True))
    assert a["candidate_count"]==len(optimizer.FAST)*len(optimizer.SLOW)
    assert a["test_used_for_selection"] is False
    assert [x["score"] for x in a["candidates"]]==[x["score"] for x in b["candidates"]]
    assert [(x["fast"],x["slow"]) for x in a["candidates"]]==[(x["fast"],x["slow"]) for x in b["candidates"]]
    assert a["selected"] is not None
    assert b["selected"] is not None
    assert (a["selected"]["fast"],a["selected"]["slow"])==(b["selected"]["fast"],b["selected"]["slow"])
    assert a["selected"]["held_out_test"]["return_pct"]!=b["selected"]["held_out_test"]["return_pct"]

def test_private_research_persists_and_requires_explicit_save(dbs):
    a=optimizer.optimize("spy",max_drawdown_pct=30,data=synthetic())
    assert library.list_saved()==[]
    assert optimizer.load_run(a["id"])["id"]==a["id"]
    listed=optimizer.list_runs()
    assert len(listed)==1
    assert "strategy_code" not in str(listed)
    saved=optimizer.save_selected(a["id"],"Approved synthetic research")
    assert saved["name"]=="Approved synthetic research"
    assert len(library.list_saved())==1

def test_no_fabricated_or_short_data(dbs):
    with pytest.raises(HTTPException):
        optimizer.optimize("spy",data={"source":"test","bars":synthetic()["bars"][:50]})
    with pytest.raises(HTTPException):
        optimizer.optimize("spy",max_drawdown_pct=0,data=synthetic())
    invalid=synthetic()
    invalid["bars"][55]["close"]=float("nan")
    with pytest.raises(HTTPException):
        optimizer.optimize("spy",data=invalid)
