from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend import ledger
from backend.ledger import fee_for, modeled_fill, positive_quantity, submit_order, account_snapshot, reset_account

def quote(price=100.0):
    return {
        "price": price, "bid": None, "ask": None, "spread_bps": 10,
        "tradable": True, "source": "unit-test", "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@pytest.fixture(autouse=True)
def temporary_database(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ledger, "DB_PATH", tmp_path / "trading.sqlite3")

def test_buy_sell_and_persistence():
    buy = submit_order("aapl", "buy", "10", quote())
    assert buy["price"] > 100
    assert buy["fee"] == 1.0
    account = account_snapshot({"aapl": quote()})
    assert account["positions"][0]["quantity"] == 10
    assert account["cash"] < 99000
    sell = submit_order("aapl", "sell", "4", quote())
    assert sell["price"] < 100
    account = account_snapshot({"aapl": quote()})
    assert account["positions"][0]["quantity"] == 6
    assert len(account["fills"]) == 2
    reset_account()
    assert account_snapshot()["cash"] == 100000
    assert not account_snapshot()["fills"]

def test_order_guards():
    with pytest.raises(HTTPException):
        submit_order("aapl", "sell", "1", quote())
    with pytest.raises(HTTPException):
        submit_order("aapl", "buy", "-1", quote())
    with pytest.raises(HTTPException):
        submit_order("aapl", "buy", "0.5", quote())
    with pytest.raises(HTTPException):
        submit_order("vfv", "buy", "1", quote())
    with pytest.raises(HTTPException):
        submit_order("aapl", "buy", "200000", quote())
    with pytest.raises(HTTPException):
        submit_order("aapl", "buy", "1", {**quote(), "tradable": False})

def test_market_spread_fills_and_fees():
    assert modeled_fill("buy", quote()) > Decimal("100")
    assert modeled_fill("sell", quote()) < Decimal("100")
    bidask = {**quote(), "bid": 99.9, "ask": 100.1}
    assert modeled_fill("buy", bidask) > Decimal("100.1")
    assert modeled_fill("sell", bidask) < Decimal("99.9")
    assert fee_for("Crypto", Decimal("1"), Decimal("10000")) == Decimal("60.00")
    with pytest.raises(HTTPException):
        positive_quantity("NaN")

def test_equity_unknown_when_position_quote_unavailable():
    submit_order("aapl", "buy", "1", quote())
    account = account_snapshot()
    assert account["has_unpriced_positions"] is True
    assert account["equity"] is None
