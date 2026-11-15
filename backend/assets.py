"""Fixed instrument registry for the first, local-only milestone.

A symbol being present does not imply its contracts can be simulated properly.
Options and futures are chart-only until contract metadata and margin are implemented.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Instrument:
    id: str
    ticker: str
    kind: str
    currency: str = "USD"
    tradable: bool = True
    decimals: int = 2
    spread_bps: float = 5.0

INSTRUMENTS: dict[str, Instrument] = {
    "aapl": Instrument("aapl", "AAPL", "Stocks", spread_bps=5),
    "nvda": Instrument("nvda", "NVDA", "Stocks", spread_bps=8),
    "tsla": Instrument("tsla", "TSLA", "Stocks", spread_bps=10),
    "msft": Instrument("msft", "MSFT", "Stocks", spread_bps=5),
    "spy": Instrument("spy", "SPY", "ETFs", spread_bps=3),
    "qqq": Instrument("qqq", "QQQ", "ETFs", spread_bps=4),
    "vfv": Instrument("vfv", "VFV.TO", "ETFs", "CAD", tradable=False, spread_bps=8),
    # Contract-less examples are explicitly unavailable, never fake live option quotes.
    "aapl-opt": Instrument("aapl-opt", "", "Options", tradable=False),
    "spy-opt": Instrument("spy-opt", "", "Options", tradable=False),
    "es": Instrument("es", "ES=F", "Futures", tradable=False),
    "nq": Instrument("nq", "NQ=F", "Futures", tradable=False),
    "eurusd": Instrument("eurusd", "EURUSD=X", "Forex", decimals=5, spread_bps=1.5),
    "gbpusd": Instrument("gbpusd", "GBPUSD=X", "Forex", decimals=5, spread_bps=2),
    "btcusd": Instrument("btcusd", "BTC-USD", "Crypto", spread_bps=10),
    "ethusd": Instrument("ethusd", "ETH-USD", "Crypto", spread_bps=12),
}

def get_instrument(asset_id: str) -> Instrument:
    from fastapi import HTTPException
    instrument = INSTRUMENTS.get(asset_id)
    if instrument is None:
        raise HTTPException(404, detail="Unknown asset.")
    return instrument
