# Research Lab and Live Engine: user workflow

This project is local-first. The desktop npm frontend and Python backend
run on the owner's computer. No Vercel deployment or live brokerage order
submission is authorized by this change.

## Two primary workspaces

**Research Lab** is an experimental environment. Its nested sections are:
- Strategy Tournament: scan the entire reference catalog for supported
  stock/ETF historical data; compare candidate multi-asset strategies;
  rank top ten by validation score, then inspect held-out results and
  hypothetical market paths
- Single-asset Research: date-selectable historical replay, charts, safe
  DSL rule editor, editable starter templates, performance analytics,
  stochastic scenario research, saved strategies, and trade history
- Portfolio Research: cash-backed, multi-asset replay; cross-symbol
  DSL templates; orders; analytics and time navigation
- Optimization & Discovery: existing single-asset SMA optimizer and
  existing five-model portfolio comparison queue, validation metrics and
  detailed model execution analysis

**Live Engine** keeps the real operational record separate:
- Overview & Actions: status and real pending recommendations, portfolio
  summary, confirmed manual fills, plus the latest top-ten *research*
  candidates clearly labeled as not actionable live orders
- Live Data & Coverage: actual provider timestamps, archived OHLCV,
  subscriptions and source health
- Strategy Engine: explicitly activate a previously reviewed, saved
  strategy for paper or live monitoring
- Execution History: manually confirmed broker fills with correction history
- Alerts & Health: worker health, rejected/stale market signals and notices

A research strategy is not automatically activated by being created,
ranked, selected, or saved. A live strategy engine never submits brokerage
orders and never assumes that a backtest entry equals a real Wealthsimple fill.

## Editable starter rule scripts

The local editor now provides ten single-asset and eight cross-asset
templates. Each is written in the existing restricted WHEN ... BUY/SELL
percentage DSL. Editing/selecting does not run arbitrary Python or trade.
Cross-asset templates are generated only from symbols in the active
portfolio replay. At most 12 distinct rules fit the supported DSL, so
the multi-asset templates include up to six symbols with two rules each.

The tournament's five allocation *models* are distinct from the editable
DSL scripts. A tournament result represents a cash-backed portfolio
allocation/rebalance policy. It is not automatically translated into a
long-form DSL suitable for unattended live execution.

## Universe scanning and top-ten ranking

Click Run universe-wide scan in Research Lab > Strategy Tournament.
The private laptop research worker receives a persisted SQLite job,
then checks the full reference catalog. The present executable study
supports USD/CAD stocks and ETFs with at least 500 authentic, sorted,
physically consistent daily candles. The full catalog includes crypto,
index, FX, and futures reference products. Unsupported contracts and
currencies are recorded as exclusions, not claimed as portfolio-tradable.
Missing market history may be requested from the unofficial public
provider; saved real Parquet OHLCV is preferred and no invented gaps
are filled. The laptop must stay online.

The study evaluates several preset diversified baskets, sector funds,
defensives, income strategies, international, momentum, hedge proxies,
and leveraged ETF baskets. It also proposes dynamic baskets screened
from real training history using a fixed calendar cutoff. For each
viable basket, it tests five previously supported portfolio models:
equal weight, inverse volatility, trend filter, relative momentum and
volatility target. Baskets contain at most ten assets to preserve the
existing validated portfolio research constraints. This is a bounded
candidate search across the catalog, **not** exhaustive optimization of
all combinatorial portfolios or all possible DSL programs.

Candidate ranking uses chronological training and validation results
only, with a drawdown limit, activity screen, turnover penalty and
validation-based score. The last ~20% of each aligned basket's observed
timeline is not used for selection. At most ten qualified candidates
are retained, and fewer may qualify. Each ranked candidate has its
final period evaluated only after selection. Held-out results are not
used to reorder the top ten.

The 30-session hypothetical scenario table resamples realized strategy
returns after the fact and introduces several shocks and a slower
execution assumption. These are *conditional stress paths*, not machine
learning point forecasts, reliable probability estimates, or future
observations. Do not interpret 5%/95% bootstrap quantiles as calibrated
market probabilities.

### Wealthsimple execution assumptions

As of November 2026, Wealthsimple's published trading account fees
state zero stock/ETF commissions and a CAD/USD conversion fee of 1.5%
when a currency exchange occurs. The tournament conservatively assumes
a CAD base account and a conversion cost when an instrument's cash
currency differs. An owner who maintains separate USD balances can
have a different realized FX profile. Broker spread and market-impact
costs are *assumptions*, not Wealthsimple quotes or promises.

The base model uses completed prior-session prices and fills at the
next common observed regular-session open. It includes an editable
one- or two-session lag, extra slippage stress, and a warning that
overnight or weekend calendar latency can exceed a 12-hour objective.
Actual partial fills, order queues, market hours, tax lots, dividends,
split adjustment, margin interest, broker availability, per-instrument
order restrictions, and foreign exchange conversions are not fully
reproduced by OHLCV alone. Wealthsimple's market order and 24-hour
limit-order rules differ by eligible security.

Wealthsimple does not currently support naked short-selling of stock
shares, according to its own trading help. The tournament cannot
issue such orders. An inverse ETF is an *independent fund* with its own
daily reset and tracking behavior, not a direct short position. Leveraged
ETFs are also shown only as restricted research. Borrowed-money leverage
and options are excluded from the cash-only scoring engine; margin
interest and liquidations require a separate audited engine. Exchange
eligibility, account type and instrument listing must be independently
checked before acting on a proposed candidate.

The tool does not pull private Wealthsimple account prices or trades.
Market history currently comes from available Yahoo/Coinbase provider
data and local Parquet; brokers may execute at different prices.

### Risk, sampling and historical completeness

The scan operates on available historical instrument symbols today;
survivorship and listing-selection bias can contaminate performance.
Raw price-only OHLCV is not a total-return series. Corporate actions,
missing bars, delayed dividends, survivorship, stale FX and trading
calendars need further audit. Report excluded symbols explicitly.
The platform must not market the ranked list as guaranteed gains,
probabilistic forecasts, or a fully broker-replicable trading plan.

## Start and inspect

~~~powershell
cd E:\Trading-Simulator
git pull
.\stop-local.ps1
.\start-local.ps1 -NoBrowser
~~~

Open the local browser at http://127.0.0.1:5173, then select Research Lab
and Strategy Tournament. Queue the scan. Completed results are visible
in the tournament and a read-only top-ten table appears in Live Engine >
Overview & Actions. The worker persists jobs in data/universe_research.sqlite3,
so navigating away does not stop the scan. Cancelling a scan prevents the
result being marked complete, but cannot forcibly interrupt an ongoing
provider HTTP request instantly.

The scan is designed for a laptop with rate-limited provider collection.
Run the optional historical bulk backfill first for better coverage.
No source files containing downloaded market data, real investment
holdings, saved strategy versions or credentials are committed.

Official Wealthsimple documentation:
- https://www.wealthsimple.com/en-ca/legal/fees/trade
- https://help.wealthsimple.com/hc/en-ca/articles/360058451433-Understanding-market-orders
- https://help.wealthsimple.com/hc/en-ca/articles/19922601555739-Place-a-24-hour-trading-order
- https://help.wealthsimple.com/hc/en-ca/articles/33646380604187-Trade-options-in-a-margin-account
