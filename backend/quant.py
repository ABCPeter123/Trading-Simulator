"""Vectorized research indicators.

Keep this module focused on arrays. The accounting/execution model stays in
Decimal for determinism and currency-safe fee handling.
"""
from __future__ import annotations

import numpy as np


def sma_crossovers(closes: list[float], fast: int, slow: int) -> np.ndarray:
    """Return next-open SMA crossover signals: +1 buy, -1 sell, 0 none.

    At index i, only closing prices through index i-1 are used. Therefore the
    signal cannot look at the execution candle (bar i) before its open.
    Complexity is O(n), rather than repeatedly summing slices of O(window).
    """
    if not 2 <= fast < slow <= 100:
        raise ValueError("Require 2 <= fast < slow <= 100.")
    prices = np.asarray(closes, dtype=np.float64)
    if prices.ndim != 1 or not np.all(np.isfinite(prices)) or np.any(prices <= 0):
        raise ValueError("Prices must be a positive finite 1D array.")
    signals = np.zeros(len(prices), dtype=np.int8)
    if len(prices) < slow + 2:
        return signals

    prefix = np.empty(len(prices) + 1, dtype=np.float64)
    prefix[0] = 0.0
    np.cumsum(prices, out=prefix[1:])

    i = np.arange(slow + 1, len(prices))
    prev_fast = (prefix[i - 1] - prefix[i - fast - 1]) / fast
    prev_slow = (prefix[i - 1] - prefix[i - slow - 1]) / slow
    curr_fast = (prefix[i] - prefix[i - fast]) / fast
    curr_slow = (prefix[i] - prefix[i - slow]) / slow

    signals[i[(prev_fast <= prev_slow) & (curr_fast > curr_slow)]] = 1
    signals[i[(prev_fast >= prev_slow) & (curr_fast < curr_slow)]] = -1
    return signals
