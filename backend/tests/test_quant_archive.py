"""Offline numerical and archival contract tests."""
import numpy as np
import pytest

from backend.archive import archive_path, archive_stats, record_history
from backend.quant import sma_crossovers
from fastapi import HTTPException


def naive_crossover(closes: list[float], fast: int, slow: int) -> list[int]:
    out = [0] * len(closes)
    for i in range(slow + 1, len(closes)):
        f_previous = sum(closes[i - fast - 1:i - 1]) / fast
        s_previous = sum(closes[i - slow - 1:i - 1]) / slow
        f_current = sum(closes[i - fast:i]) / fast
        s_current = sum(closes[i - slow:i]) / slow
        if f_previous <= s_previous and f_current > s_current:
            out[i] = 1
        elif f_previous >= s_previous and f_current < s_current:
            out[i] = -1
    return out


def test_vectorized_signals_match_reference():
    rng = np.random.default_rng(321)
    closes = np.round(100 + np.cumsum(rng.normal(0, 0.8, size=2000)), 4).tolist()
    actual = sma_crossovers(closes, 12, 35).tolist()
    assert actual == naive_crossover(closes, 12, 35)
    assert not any(actual[:36])


def test_no_lookahead_from_future_data():
    prices = [100 + i / 10 for i in range(120)]
    original = sma_crossovers(prices, 3, 7)
    changed = prices.copy()
    changed[70:] = [p * 4 for p in changed[70:]]
    second = sma_crossovers(changed, 3, 7)
    # Signal at 70 can only use closes through index 69.
    assert original[:71].tolist() == second[:71].tolist()


def test_invalid_numeric_input():
    with pytest.raises(ValueError):
        sma_crossovers([100, float("nan"), 102], 2, 3)
    with pytest.raises(ValueError):
        sma_crossovers([100, 101, 102], 10, 3)


def test_parquet_archive_and_duckdb_stats(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADING_SIM_MARKET_DIR", str(tmp_path))
    def make_bar(t: int, close: float):
        return {"time": t, "open": close, "high": close + 1,
                "low": close - 1, "close": close, "volume": 150}
    batch = {"asset_id": "aapl", "range": "1Y", "is_demo": False,
             "bars": [make_bar(120, 11), make_bar(60, 10)]}
    record_history(batch)
    record_history({**batch, "bars": [make_bar(120, 13), make_bar(180, 15)]})
    path = archive_path("aapl", "1Y")
    assert path.exists()
    data = archive_stats("aapl", "1Y")
    assert data["bars"] == 3
    assert data["first_timestamp"] == 60
    assert data["last_timestamp"] == 180
    assert data["highest_price"] == 16
    assert data["lowest_price"] == 9

    with pytest.raises(HTTPException) as caught:
        archive_stats("tsla", "1Y")
    assert caught.value.status_code == 404


def test_does_not_archive_demo_bars(monkeypatch, tmp_path):
    monkeypatch.setenv("TRADING_SIM_MARKET_DIR", str(tmp_path))
    record_history({"asset_id": "aapl", "range": "1M", "is_demo": True,
                    "bars": [{"time": 1, "open": 10, "high": 11, "low": 9,
                              "close": 10, "volume": 15}]})
    assert not archive_path("aapl", "1M").exists()

def test_offline_fallback_uses_only_archived_real_bars(monkeypatch, tmp_path):
    from backend import market
    monkeypatch.setenv("TRADING_SIM_MARKET_DIR", str(tmp_path))
    record_history({"asset_id": "aapl", "range": "1Y", "is_demo": False, "bars": [
        {"time": 1000, "open": 12.0, "high": 13.0, "low": 11.0, "close": 12.5, "volume": 100.0},
    ]})

    def unavailable(_instrument, _window):
        raise HTTPException(503, detail="Provider unavailable")
    monkeypatch.setattr(market, "yahoo_candles", unavailable)
    market.clear_cache()
    data = market.history("aapl", "1Y")
    assert "offline" in data["source"].lower()
    assert data["offline_cache"] is True
    assert data["is_demo"] is False
    assert data["bars"][0]["close"] == 12.5
    market.clear_cache()


def test_no_fake_fallback_if_archive_missing(monkeypatch, tmp_path):
    from backend import market
    monkeypatch.setenv("TRADING_SIM_MARKET_DIR", str(tmp_path))
    monkeypatch.setattr(market, "yahoo_candles", lambda *_: (_ for _ in ()).throw(HTTPException(503, detail="Down")))
    market.clear_cache()
    with pytest.raises(HTTPException) as caught:
        market.history("tsla", "1Y")
    assert caught.value.status_code == 503
    market.clear_cache()
