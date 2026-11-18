# High-performance portfolio discovery (local research)

This is an optional research objective within **Research Lab > Strategy Tournament**.
It evaluates portfolio models and instruments using real historical daily price observations,
the existing open-price execution simulator, model costs, and a strictly chronological
training/validation/held-out partition. It never sends broker orders.

## What is implemented

- The existing **balanced** tournament score remains available and unchanged by default
  at the backend API level, including the original 60/20/20 chronological partition.
- **High-performance discovery** computes geometric annualized compound growth (CAGR)
  and excess-return Sharpe on the validation equity curve, using an explicitly supplied
  constant annual risk-free-rate assumption. The first simulated session is compared
  with the starting virtual equity; no cash interest is credited.
- The validation score combines bounded normalized growth and Sharpe objectives and
  subtracts drawdown, execution turnover and negative validation-subperiod penalties.
  A high single-period return cannot receive unlimited extra scoring credit.
- Three sequential, nonoverlapping validation windows are analyzed for stability.
  The model is **not retrained** between windows. The windows are dependent parts
  of the same validation path. At least 90 validation sessions are required for this mode.
- The final 20% held-out segment is **never** used in instrument selection,
  basket selection, objective scoring, or portfolio ranking. It is evaluated
  only for the selected diverse shortlist, with a separate slower-fill stress test.
- Reports distinguish validation growth/Sharpe from held-out growth/Sharpe,
  observed target status, validation-window consistency, and the two-objective
  Pareto frontier for all eligible validation candidates.
- A candidate's held-out target status is only evaluated if the held-out sample
  contains at least 126 sessions. This is descriptive historical evidence,
  not a multi-year guarantee.
- For the five standard long-only models, research can optionally target
  up to 100% invested capital, permit 100% equity-class exposure, and
  redistribute unused allocation while honoring maximum position size,
  other asset-class ceilings, and the model's eligible-asset signals.
  Advanced borrowing, short and hedging models keep their own budgets.
- Existing owner research results and strategy versions remain in local
  Git-ignored SQLite storage. No private results are published to GitHub,
  CI artifacts, or the public demonstration.

## What is *not* implemented

This milestone does **not** fit new model parameters, optimize blended
strategy sleeves, correct selection metrics for an arbitrary number of
trials using Deflated Sharpe or PBO, calibrate historical term-structure
cash yields, control survivorship bias, or demonstrate consistently high
annual returns. The risk-free rate is a constant assumption for metric
calculation, not a backfilled cash-yield curve.

The immediate next milestones are true rolling walk-forward optimization,
a parameter/strategy-combination generator with explicit trial accounting,
and delayed-execution paper forward monitoring. Only after those are
validated should risk-controlled leverage be evaluated in research.

## Data and statistics conventions

CAGR: `(last_marked_equity / starting_equity) ** (252 / number_of_sessions) - 1`.

Annualized excess Sharpe:
`(mean(daily_net_returns) - daily_equivalent_cash_rate) / stdev(daily_net_returns) * sqrt(252)`.
The assumed annual cash rate is converted into an effective per-session rate.

The backtest uses actual shared daily bars with signals reading only
previous completed closes; trade prices include modeled spreads, slippage,
FX conversion, and financing where applicable.

Optimization targets do not imply a forecast, statistical confidence,
or an achievable future return. Never describe a high research score as
a trading recommendation without forward evaluation.
