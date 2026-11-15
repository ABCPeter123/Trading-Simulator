from datetime import datetime, timezone
from fastapi.testclient import TestClient
from backend.main import app
from backend import strategy

client = TestClient(app)

def test_health():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "local"

def test_backtest_without_lookahead(monkeypatch):
    candles = []
    prices = [100.0] * 34 + [103.0, 106.0, 109.0, 112.0, 115.0, 118.0]
    for i, price in enumerate(prices):
        candles.append({"time": 1700000000 + i * 86400, "open": price, "high": price + 1, "low": price - 1, "close": price, "volume": 1000})
    monkeypatch.setattr(strategy, "history", lambda asset_id, window: {"bars": candles, "source": "test"})
    result = strategy.sma_backtest("aapl", fast=2, slow=4)
    assert result["trades"]
    assert result["trades"][0]["time"] == candles[35]["time"]  # crossing at bar 34 close, filled bar 35 open
    assert result["equity_curve"][-1]["value"] > 0
