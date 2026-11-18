"""Independent synthetic broker statement comparison, no owner CSV files."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import broker_reconciliation as reconcile, live_machine as machine, main


def statement(ref=None,price=100,fee=1,quantity=10,day="2026-11-18",**extra):
    obj={"symbol":"spy","side":"buy","quantity":quantity,
         "price":price,"trade_date":day,"currency":"USD"}
    if fee is not None:obj["fee"]=fee
    if ref:obj["broker_ref"]=ref
    obj.update(extra)
    return obj


def journal(ref=None,price=100,fee=1,quantity=10,fill_id="fill-1",symbol="spy",
            executed="2026-11-18T14:30:00Z"):
    return {"id":fill_id,"signal_id":None,"asset_id":symbol,"side":"buy",
            "quantity":quantity,"price":price,"fee":fee,"currency":"USD",
            "executed_at":executed,"broker_ref":ref}


def test_exact_broker_reference_then_conservative_field_matching():
    entries=[journal(ref="synthetic-a",fill_id="a"),
             journal(fill_id="b",symbol="qqq",price=120,fee=0)]
    rows=[statement(ref="synthetic-a"),statement(
        symbol="qqq",price=120,fee=None),statement(symbol="aapl",price=50)]
    copy=deepcopy(entries)
    result=reconcile.reconcile(rows,entries)
    assert result["read_only"] and not result["import_persisted"]
    assert result["summary"]["matched"]==2
    assert result["summary"]["not_in_journal"]==1
    assert result["summary"]["journal_not_in_import"]==0
    assert result["reviews"][0]["match_type"]=="broker_reference"
    assert result["reviews"][1]["match_type"]=="symbol_side_date_quantity_price"
    assert entries==copy


def test_fee_price_and_quantity_differences_never_edit_journal():
    f=journal(ref="synthetic-a",price=100,fee=2,quantity=10)
    rows=[statement(ref="synthetic-a",price=101,fee=1,quantity=11)]
    result=reconcile.reconcile(rows,[f])
    assert result["summary"]["matched_with_differences"]==1
    assert set(result["reviews"][0]["differences"])=={"price","quantity","fee"}
    assert result["reviews"][0]["journal_price"]==100


def test_ambiguous_duplicate_and_unmatched_journal_are_not_auto_matched():
    duplicate=[journal(fill_id="a"),journal(fill_id="b")]
    result=reconcile.reconcile([statement()],duplicate)
    assert result["summary"]["ambiguous"]==1
    assert result["summary"]["journal_not_in_import"]==2
    refs=[journal(ref="synthetic-a",fill_id="a")]
    result=reconcile.reconcile([statement(ref="synthetic-a"),
                                statement(ref="synthetic-a")],refs)
    assert result["summary"]["matched"]==1
    assert result["summary"]["duplicate_statement_rows"]==1
    colliding=[journal(ref="synthetic-b",fill_id="a"),
               journal(ref="synthetic-b",fill_id="b")]
    assert reconcile.reconcile([statement(ref="synthetic-b")],colliding)["summary"]["ambiguous"]==1


def test_new_york_trade_date_is_not_naive_utc_date():
    f=journal(ref="synthetic-a",executed="2026-11-19T00:30:00Z")
    assert reconcile.reconcile([statement(ref="synthetic-a")],[f])["summary"]["matched"]==1
    with pytest.raises(HTTPException):
        reconcile.reconcile([statement(executed_at="2026-11-19T00:30:00Z",
                                       trade_date="2026-11-19")],[f])


@pytest.mark.parametrize("changes",[
    {"currency":"CAD"},{"quantity":float("nan")},{"price":0},
    {"side":"short"},{"symbol":"invalid ticker"},{"trade_date":"11/18/2026"},
    {"executed_at":"2026-11-18T11:00:00"},{"fee":float("inf")},
])
def test_invalid_normalized_import_fails_closed(changes):
    with pytest.raises(HTTPException) as error:
        reconcile.reconcile([statement(**changes)],[journal()])
    assert error.value.status_code==422


def test_partial_import_does_not_mark_unlisted_broker_trades_missing():
    rows=[statement()]
    fills=[journal(fill_id="today"),journal(fill_id="yesterday",
                      executed="2026-11-17T15:00:00Z"),
           journal(fill_id="same-day-other",symbol="qqq")]
    result=reconcile.reconcile(rows,fills)
    assert result["summary"]["matched"]==1
    assert result["summary"]["journal_not_in_import"]==1
    assert result["journal_not_in_import"][0]["fill_id"]=="same-day-other"
    assert "no journal edits" in result["limitations"].lower()


def test_private_reconciliation_api_and_no_persistence(tmp_path,monkeypatch):
    monkeypatch.setattr(machine,"DB_PATH",tmp_path/"confirmed_journal.sqlite3")
    monkeypatch.setattr(main,"PUBLIC_DEMO",False)
    client=TestClient(main.app)
    ok=client.post("/api/live/journal/reconcile",json={"rows":[statement()]})
    assert ok.status_code==200
    assert ok.json()["summary"]["not_in_journal"]==1
    assert machine.journal()["fills"]==[]
    monkeypatch.setattr(main,"PUBLIC_DEMO",True)
    denied=client.post("/api/live/journal/reconcile",json={"rows":[statement()]})
    assert denied.status_code==403
    assert not any("statement" in x.name for x in tmp_path.iterdir())
