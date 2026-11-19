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
- A shortlisted standard long-only strategy imported into the private strategy
  library retains its research investment target, equity cap and
  redistribution preference. Historical portfolio replay reads those
  exact allocation parameters, although its separate fill/accounting
  ledger can still produce different realized results.
- Live monitoring currently rejects custom exposure configurations it
  cannot reproduce. Saving a strategy does not constitute live approval.
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


## Portfolio rebalance frequency

The Strategy Tournament Test Ground now supports **daily (1)**, **weekly (5)**
and **monthly (21)** shared-session rebalance checks. The UI defaults to weekly
for **new** scans. Previously saved scans and imported strategies keep their
original 21-session cadence unless a new study is explicitly created.

The selected cadence travels with each private tournament strategy version
and its subsequent date-scoped study, historical replay, walk-forward
selection, forward-paper ledger or compatible live monitoring. Daily bars
support at most one new portfolio allocation decision for each completed
session; a check can produce zero orders when target weights do not change.
The number of executed orders is not a user-specified trading quota.

The engine continues to use **completed daily closes** and modeled **next
open / second next open** fills, with configurable slippage, FX and commissions.
Neither a daily cadence nor several individual asset orders during a daily
rebalance represents an intraday multi-signal strategy. Intraday portfolio
backtesting requires synchronized 15-minute/hourly data, appropriately lagged
features and independent fill and liquidity assumptions before it can be
presented as tested. Higher cadence increases possible turnover and modeled
costs; compare candidates on identical assumptions.

## Intraday portfolio research with observed minute candles

**Strategy Tournament → selected strategy → Walk-forward & tools → Intraday
portfolio test** opens a separate, private, durable historical study. It uses
actual recorded provider candles via `backend/intraday.py`, with:

- **1 minute:** up to 7 calendar days.
- **5 or 15 minutes:** up to 60 calendar days.
- **1 hour:** up to 2 years, subject to what the provider actually returns.
- **One, two, or four** shared portfolio allocation checks per market day, at
  regular US-session times. One allocation check can yield multiple orders or
  no order when portfolio targets are unchanged.

USD-funded portfolios can now use the five standard cash-only models or
long-only shared-cash model blends. USD- and CAD-listed stocks and ETFs are
supported when their actual minute candles overlap. CAD prices are converted
into USD using the **previous completed daily USD/CAD close**, never the
contemporaneous or future daily rate. Rate observations older than five
calendar days are rejected. CAD orders incur the explicit per-order FX
conversion bps in addition to spread, slippage and commissions. The report
records the real daily FX source and whether it came from a local snapshot.
There is **no interpolated intraday FX**. Short-share, margin, CAD funding and
asynchronous unmatched price paths remain unsupported and are rejected rather
than silently rerouted through the daily engine.

At the opening of a shared intraday candle, the selected allocation model
observes **only prior completed shared closes**. It computes target cash
positions on those observed bars and simulates sells then buys at the current
candle's provider open, plus estimated spread, slippage and commission.
The baseline uses an identical basket, cash ledger, timestamps, limits,
decision cadence and execution costs. Missing per-asset candle timestamps are
not forward-filled, and partial/uncompleted bars are excluded. The report
records source names, offline-cache provenance, common-bar coverage, full
realized order count, drawdown, turnover, fees and account-value paths.

Important: this re-evaluates **intraday bar-period indicators**, not the
unchanged daily strategy. For example, the trend filter's 126-period moving
average becomes 126 intraday bars, not 126 days. It is **exploratory research**,
not a new walk-forward optimizer, sealed audit, live trading signal or
validated intraday market-impact model. Annual CAGR and Sharpe are deliberately
not reported for short intraday samples. The existing historical daily
tournament and paper-forward results stay separate and unchanged. The
simulator never places real broker orders.

## Candidate quality and benchmark-aware tournament ranking

The tournament now includes two additional general-purpose cash-funded
allocation methods: **adaptive momentum** (positive absolute medium-term
trend plus ranked strength, with an optional real defensive sleeve) and
**pullback in trend** (short-term price weakness within a positive
long-horizon trend). These are fixed research algorithms, not learned
predictions or owner-fitted private trading rules. Both use previously
completed OHLC observations and existing position/asset-class exposure caps.
On intraday bars, their lookback lengths are measured in bars, not days.

Each basket's **validation-period** equal-weight control is independently
replayed using the same shared cash, dates, position limits and estimated
trading costs. A candidate that lags that control in return or excess
Sharpe receives an inspectable soft ranking penalty. The penalty does
not read from held-out dates. Balanced research also penalizes losing
validation subwindows, instead of relying on overall return alone. Baskets of
highly correlated instruments receive a small additional debit computed from
**training-only** realized pairwise daily returns; this does not guarantee
future diversification or cover issuer/factor overlap.

The displayed **Top 10** now means the actual ten highest validation
scores, not a forced one-per-family shortlist. A separate explicit
quality label states whether a displayed candidate beat its basket
reference on **both** return and excess Sharpe during validation.
A candidate lacking both advantages is *not yet demonstrated* to
have a superior trading rule; its positive raw or audit return alone
must not be interpreted as evidence of an edge.

The original sealed test window, selection protocol, private source
storage, risk constraints and human-approved execution boundaries are
unchanged. These modifications increase selection rigor but do not
guarantee higher unseen returns or a usable strategy. Previously
completed private research and frozen strategy versions remain unchanged;
new rules take effect on **new** research scans.
