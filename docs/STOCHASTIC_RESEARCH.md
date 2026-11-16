# Stochastic Scenario Research

The **Scenario Research** tab in both saved Arcade simulation modes
provides reproducible hypothetical price-path research. It uses only
observed historical closing prices through the currently revealed candle.

## Stochastic path methodology

The model fits consecutive observed-candle log returns

`r_t = ln(S_t/S_(t-1))`

using a rolling window of 20-252 returns and estimates their sample mean
`m` and standard deviation `s`. It generates 256 independent synthetic
geometric Brownian motion scenarios:

`S_(t+1) = S_t * exp(m + s*Z_t)`, where `Z_t ~ N(0,1)`.

The model is calibrated to empirical physical drift, not a risk-neutral
option-pricing measure. Each run is reproducible from a fixed seed and
contains 256 paths of 1-60 future *replay bars*, with P05, P25, median,
P75, P95 curves and both theoretical/model and simulated fractions of
paths that end above today's price. The chart plots 16 representative
paths plus percentile curves calculated from **all 256 paths**.

The tool never reads unrevealed future market candles to calibrate drift,
volatility, or price scenarios.

This is **not a prediction of future stock returns**. The GBM assumptions
of constant parameters, independent lognormal shocks, no jumps and no
fat tails are especially fragile around earnings, crises, market opening
gaps and illiquid intraday prices. Percentiles are conditional model
outputs, not reliable calibrated coverage probabilities.

## Forecast-aware strategy signal

Existing strategy syntax accepts a historical-model probabilistic
indicator:

```text
WHEN PROB_UP(20) CROSSES ABOVE 60 BUY 25%
WHEN PROB_UP(20) CROSSES BELOW 40 SELL 100%
```

For a multi-asset portfolio:

```text
WHEN spy PROB_UP(20) CROSSES ABOVE 60 BUY 25% qqq
WHEN spy PROB_UP(20) CROSSES BELOW 40 SELL 100% qqq
```

`PROB_UP(h)` estimates `Pr[S_(t+h) > S_t]` from an assumed normal
distribution of **observed log returns**, using up to 60 prior returns
and an estimated drift/volatility. The return is a percentage 0-100.
`h` must be 1-60, measured in replay candles, not calendar days. The
indicator never uses the 256 random future paths during strategy execution.
It is deterministic per revealed bar so backtests can be reproduced.

An order triggers only when the percentage crosses a threshold according
to the original edge-triggered strategy DSL. Orders still fill no earlier
than the next actual historical candle for the traded symbol. The model
can be wrong, and no order promises a portfolio target allocation.

## Black-Scholes calculator

Scenario Research includes an optional separate **European vanilla option
valuation** calculator using the Black-Scholes-Merton formula with an
assumed risk-free rate, strike, expiry time in years and annual implied
volatility input. The calculator returns theoretical call and put prices.

Black-Scholes uses risk-neutral pricing and **does not predict underlying
future asset prices**. The volatility input is a manual assumption;
minute-level historical volatility is not automatically annualized by
guessing the number of trading sessions. The valuation ignores
American exercise, dividends unless supplied in the API, discrete
hedging, jumps, implied volatility smiles, liquidity and transaction costs.

## Endpoints and tests

- `POST /api/research/scenarios`: mode, run ID, selected basket asset,
  lookback, horizon, optional repeatable seed.
- `POST /api/research/black-scholes`: spot, strike, maturity years,
  annual volatility, rate, optional dividend yield.
- `backend/stochastic.py`: model, probability indicator and BSM equations.
- `backend/tests/test_stochastic_navigation.py`: reproducibility,
  percentile order, no future bars, safe DSL and put-call parity.

All calculations run locally and require no external prediction service,
paid API, new npm package or new Python dependency.
