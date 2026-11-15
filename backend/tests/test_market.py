from datetime import datetime, timedelta, timezone
import math

import pandas as pd
from backend import market
from backend.assets import get_instrument

def test_session_gate_weekend_and_fx_rollover():
    friday_open = datetime(2026, 11, 13, 15, 0, tzinfo=timezone.utc)
    sunday_before_fx = datetime(2026, 11, 15, 20, 0, tzinfo=timezone.utc)
    sunday_after_fx = datetime(2026, 11, 15, 23, 0, tzinfo=timezone.utc)
    assert market.market_open(get_instrument("aapl"), friday_open)
    assert not market.market_open(get_instrument("aapl"), sunday_after_fx)
    assert not market.market_open(get_instrument("eurusd"), sunday_before_fx)
    assert market.market_open(get_instrument("eurusd"), sunday_after_fx)
    assert market.market_open(get_instrument("btcusd"), sunday_before_fx)

def test_yahoo_missing_volume_keeps_legitimate_fx_bars(monkeypatch):
    class FakeTicker:
        def history(self, **kwargs):
            dates = pd.to_datetime(["2026-11-13T12:00:00Z", "2026-11-13T13:00:00Z"])
            return pd.DataFrame({
                "Open": [1.08, 1.081], "High": [1.081, 1.082],
                "Low": [1.079, 1.080], "Close": [1.0805, 1.0815],
                "Volume": [float("nan"), 0],
            }, index=dates)
    monkeypatch.setattr(market.yf, "Ticker", lambda _: FakeTicker())
    bars = market.yahoo_candles(get_instrument("eurusd"), "1M")
    assert len(bars) == 2
    assert bars[0]["volume"] == 0.0
    assert bars[0]["close"] == 1.0805

def test_coinbase_candle_column_order(monkeypatch):
    now = int(datetime.now(timezone.utc).timestamp()) - 60
    class Response:
        def raise_for_status(self):
            pass
        def json(self):
            return [[now, 99, 105, 101, 103, 50]]
    class FakeClient:
        def get(self, *_args, **_kwargs):
            return Response()
    monkeypatch.setattr(market, "_client", FakeClient())
    bars = market.coinbase_candles(get_instrument("btcusd"), "1D")
    assert bars
    assert bars[-1]["low"] == 99
    assert bars[-1]["high"] == 105
    assert bars[-1]["open"] == 101
    assert bars[-1]["close"] == 103
    assert bars[-1]["volume"] == 50
