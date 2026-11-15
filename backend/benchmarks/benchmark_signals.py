"""Compare reference SMA signal loops with the vectorized NumPy kernel.

Run:
    python -m backend.benchmarks.benchmark_signals
Measurements include only signal calculation, not data downloads, DB or trades.
Synthetic prices are used solely for this benchmark, never for user charts.
"""
from statistics import median
from time import perf_counter

import numpy as np

from backend.quant import sma_crossovers


def reference(closes: list[float], fast: int, slow: int) -> list[int]:
    signals = [0] * len(closes)
    for i in range(slow + 1, len(closes)):
        prev_fast = sum(closes[i-fast-1:i-1]) / fast
        prev_slow = sum(closes[i-slow-1:i-1]) / slow
        curr_fast = sum(closes[i-fast:i]) / fast
        curr_slow = sum(closes[i-slow:i]) / slow
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            signals[i] = 1
        elif prev_fast >= prev_slow and curr_fast < curr_slow:
            signals[i] = -1
    return signals


def elapsed(fn, repeats: int = 3) -> float:
    samples = []
    for _ in range(repeats):
        before = perf_counter()
        fn()
        samples.append(perf_counter() - before)
    return median(samples)


def main() -> None:
    rng = np.random.default_rng(2026)
    for count in (5_000, 50_000, 250_000):
        # Only benchmark the same, finite positive synthetic price array.
        prices = (100 + np.cumsum(rng.normal(0, 0.002, count))).tolist()
        fast, slow = 10, 70
        expected = reference(prices, fast, slow)
        actual = sma_crossovers(prices, fast, slow)
        if expected != actual.tolist():
            raise AssertionError("Optimized kernel does not match reference.")
        old_s = elapsed(lambda: reference(prices, fast, slow))
        new_s = elapsed(lambda: sma_crossovers(prices, fast, slow))
        print(
            f"{count:>9,} bars | old: {old_s*1000:>8.2f} ms "
            f"| numpy: {new_s*1000:>8.2f} ms | speedup: {old_s/new_s:>6.1f}x"
        )


if __name__ == "__main__":
    main()
