"""No-network tests of ticker discovery and persisted instrument imports."""
from fastapi import HTTPException
from backend import assets
import pytest


class SearchResult:
    quotes = [
        {"symbol": "QWER", "quoteType": "EQUITY", "shortname": "Example Holdings", "currency": "USD", "exchange": "NMS"},
        {"symbol": "NVT.TO", "quoteType": "ETF", "longname": "Canadian Example", "currency": "CAD", "exchange": "TOR"},
        {"symbol": "INDEX123", "quoteType": "INDEX", "shortname": "Example Index"},
        {"symbol": "BAD/QUERY", "quoteType": "EQUITY", "shortname": "Invalid Symbol"},
    ]


def fake_search(_query, **_kwargs):
    return SearchResult()


@pytest.fixture
def custom_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(assets, "_CUSTOM_PATH", tmp_path / "custom_instruments.json")
    monkeypatch.setattr(assets.yf, "Search", fake_search)
    yield


def test_search_filters_unexpected_security_type(custom_registry):
    discovered = assets.search_yahoo("QWER")
    assert len(discovered) == 3
    assert discovered[0]["symbol"] == "QWER"
    assert discovered[0]["asset_class"] == "Stocks"
    assert discovered[1]["currency"] == "CAD"
    assert discovered[2]["asset_class"] == "Indices"


def test_custom_ticker_import_is_persistent_and_currency_safe(custom_registry):
    usd = assets.import_yahoo("QWER")
    assert usd["tradable"]
    assert usd["asset_class"] == "Stocks"
    assert usd["currency"] == "USD"
    assert assets.get_instrument(usd["id"]).ticker == "QWER"
    assert assets._CUSTOM_PATH.exists()
    assert assets.import_yahoo("QWER")["id"] == usd["id"]
    cad = assets.import_yahoo("NVT.TO")
    assert not cad["tradable"]
    assert cad["currency"] == "CAD"
    idx = assets.import_yahoo("INDEX123")
    assert not idx["tradable"]
    assert idx["asset_class"] == "Indices"
    assert len(assets.list_instruments("custom_")) >= 3


def test_unverified_ticker_cannot_be_imported(custom_registry):
    with pytest.raises(HTTPException) as ex:
        assets.import_yahoo("MISSING")
    assert ex.value.status_code == 404
    with pytest.raises(HTTPException):
        assets.import_yahoo("https://bad.example")
