# Multi-asset portfolio research

**Primary research scope: a diversified portfolio, not one instrument.**
Trading Simulator compares allocations across a basket of stocks, ETFs,
bond funds, commodities funds, REIT funds and optional cryptocurrencies.
The legacy SMA single-asset optimizer remains available in a secondary tab
for backward compatibility, but must not dictate future research architecture.

## Five separately evaluated portfolio allocation models

1. **Equal weight:** rebalance capital equally across the basket, then
   respect position limits and group concentration caps.
2. **Inverse volatility:** allocate more to assets with lower trailing
   60-session daily volatility.
3. **Trend filtered:** inverse-volatility allocation only when the last
   completed close is above the trailing 126-session average.
4. **Relative momentum:** rank the last completed 3- and 6-month returns,
   allocate to the strongest positive-momentum subset, and keep spare cash.
5. **Volatility target:** inverse-volatility with a maximum 12% annualized
   estimated portfolio volatility budget, scaling invested exposure down
   when realized risk is high.

All rules are predefined public research families. Actual winning models,
scores, parameters, research sessions and execution data stay on the
private Windows PC, never in a public test fixture or Git commit.

## Queue portfolio research from the website

The preferred workflow is **web controlled, Windows executed, private SQLite
persisted**. The Vercel website never runs computational Python, stores
job parameters, or receives Vercel-side copies of research results.

1. Update `E:\\Trading-Simulator` with `git pull`, then **restart**
   `start-private-bridge.ps1`. The launcher starts both FastAPI and a
   dedicated `backend.research_worker` Python process. Existing bridge
   sessions and tunnel publication behavior remain unchanged.
2. Open the permanent Trading Simulator website, enter the shared password,
   and navigate to **Strategy Discovery > Portfolio research, multi-asset**.
3. Select 2-10 supported USD instruments and the two risk limits.
   Select **Queue research on laptop**. The request returns immediately
   with a durable job ID, not a long-running HTTP calculation.
4. Watch progress in **Laptop research queue**. Jobs progress through
   queued, running, completed, failed or cancelled. The UI polls every
   five seconds while open. It can be closed, reloaded or reopened on
   another device with the same private-password login.
5. Open the completed study to inspect full saved performance, correlation
   matrices, holdings, executions and model rankings. Use **Cancel research**
   on queued/running jobs if desired. Cancellation happens at safe
   checkpoints between market downloads and model evaluations.

The queue has a bounded capacity of 20 unfinished jobs. A restarted worker
recovers stale interrupted jobs after 30 minutes, and uses the job ID as the
saved research run ID so it can link an already persisted result without
recomputation. It performs at most one study at a time. Jobs contain
only a validated research configuration, never arbitrary shell commands,
Python programs or browser-supplied price history.

**Local files**:

- `data/research_queue.sqlite3`: queue, job state, timestamps and progress
- `data/portfolio_research.sqlite3`: private completed study details
- `.local-state/private-bridge/research.stderr.log`: credential-free worker logs

A laptop that is asleep, powered off or whose private bridge is stopped
cannot accept website requests and will not run research. Jobs already
queued remain durable and run when the bridge and worker are restarted.
Vercel is a static frontend and address lookup, **not a cloud job broker**.
A request must reach the laptop once to enter its local queue.

The browser uses the same existing password-protected tunnel as other
private functions. The shared password grants full access to the private
workspace, including research, so share it only with trusted people. The
server rejects all research jobs in public-demo mode. Research does not
run on the Vercel deployment or GitHub Actions.

## Analyze your basket on Windows

Pull latest changes:

```powershell
cd E:\\Trading-Simulator
git pull
```

In the website, open **Strategy Discovery** and use the default
**Portfolio research, multi-asset** tab. A sample *research-only* basket
is `SPY, QQQ, IEF, GLD, EEM, VNQ`, which gives exposure to US stocks,
technology, intermediate US Treasuries, gold, emerging markets and real
estate. Choose your own basket of 2-10 USD-listed supported instruments.
For an additional crypto asset, append `BTCUSD`.

Alternatively, run directly in a PowerShell window:

```powershell
powershell -ExecutionPolicy Bypass -File .\\start-live-machine.ps1 -ComparePortfolio
```

For a chosen basket:

```powershell
powershell -ExecutionPolicy Bypass -File .\\start-live-machine.ps1 -ComparePortfolio -PortfolioAssets "spy,qqq,ief,gld,eem,vnq,btcusd"
```

For a **one-time email** with the saved portfolio results included in the
existing complete trading briefing, use `-EmailPortfolioStudy` along
with `-ComparePortfolio`. It asks for approval before sending:

```powershell
powershell -ExecutionPolicy Bypass -File .\\start-live-machine.ps1 -ComparePortfolio -EmailPortfolioStudy
```

This uses your existing local Gmail SMTP setup if authenticated. No
trading data is uploaded to Vercel. The regular weekday email digest
also includes summary statistics from the three most recent portfolio
research runs, including validation rankings and selected held-out
results. Research calculations are on demand, not repeatedly retrained
at every worker tick.

## Backtest integrity and methodology

- Six years of live API data are **not** guaranteed. The research engine
  requests `5Y` of daily, actual candles per asset. The actual overlapping
  session count and date bounds are displayed.
- At least 450 real overlapping sessions must exist, with 180 sessions
  of historical warmup. No missing candles are backfilled.
- Segmentation: first 60% of available aligned sessions for training,
  next 20% for validation, final 20% as one held-out test. Only training
  and validation scores choose the model. The selected model's held-out
  test is evaluated once after selection.
- At a hypothetical rebalance, signals use **only completed previous
  session closes**. Fills occur at the **next common-session open**,
  not at the signal close. No future bar is used to calculate a weight.
- Shared cash across the entire basket, long-only, no borrowing, monthly
  21-session rebalancing. Fractional shares modeled for crypto;
  integer stock and ETF shares.
- Simplified estimated trading friction: instrument spread, 2 bps
  slippage, and $1 minimum or $0.005/share commission. These are not
  executable quotes or a complete cost model.
- Maximum configured single-position exposure is 5-50%. Additional
  coarse group caps: equities 70%, bonds 55%, commodity ETFs 35%,
  real estate 20% and crypto-related exposure 10%. Unallocated cash is retained rather than force invested.
  The group classifier is a simple instrument-category mapping,
  **not** an audited look-through of ETF constituents or correlations.
- Fees, turnover, net returns, Sharpe, drawdown, actual portfolio weights,
  equal-weight comparison and correlation matrix are displayed. The
  correlation matrix uses historical training/validation data only.
- Crypto weekends are excluded in baskets mixed with exchange-day
  assets to maintain a shared execution timeline.
- Fees and prices are measured in USD. This first version does not
  compare Canadian-dollar funds without historical FX conversion.

## What remains separate

Research does **not** silently modify the live trading strategy or
place broker orders. The existing saved executable portfolio strategy
language supports separate rules for a basket, but these five portfolio
allocation models are **not automatically translated** to executable
rules or deployed to the live worker. Forward-paper monitoring,
broker-confirmed executions, and research models remain separate
systems. They must be explicitly validated and approved before live
deployment support is added.

This is historical hypothesis testing, not proof of profitable
future returns. Corporate actions, dividends, full liquidity/market
impact, slippage in stressed markets, interest on cash, margin, taxes,
currency hedging and optimized cross-currency execution need
additional research before treating these outputs as broker-ready.

## Where results are saved

Private local file:

`E:\\Trading-Simulator\\data\\portfolio_research.sqlite3`

Every portfolio study includes the basket, source names, number of
overlapping real sessions, all validation rankings, a selected
held-out-test equity curve, the equal-weight comparison, weights,
trades, risk statistics and correlation matrix. The file is Git-
ignored and stays on your desktop. Preserve an encrypted backup.


## Research robustness extension (local only)

Universe-wide studies now accept explicit **account funding currency (USD by default)**,
per-order commission, slippage in basis points, and cross-currency conversion bps.
USD-funded USD instruments do not incur a synthetic CAD conversion. A conversion
assumption applies only when an instrument's recorded currency differs from the
funding currency. The settings are stored with each private job so old studies
retain their original parameters; rerun a study to compare new assumptions.

Enable **shared-cash blended candidates** to test bounded two- or three-sleeve
long-only combinations of momentum, trend, equal-weight and defensive models.
Every sleeve generates its allocation using completed historical observations,
then the allocation engine nets orders in one common cash ledger, with fees paid
once. These blends are **historical research only**. They now have immutable private
saved versions, exact code-source inspection, date-scoped analysis, and
walk-forward revalidation. They remain prohibited from interactive cash replay
and live monitoring, which do not yet reproduce their sleeve-combination rules.
Margin and short models remain separate signed-ledger research.

The universe study reports a **validation-only score breakdown**. Growth, Sharpe,
drawdown, turnover, subperiod consistency and other deductions appear separately.
Held-out results do not influence ranking. The score is a heuristic, not a
probability of profitability. It also reports separate explicit charges and
estimated spread/slippage implicit in historical fill prices; do not add implicit
costs to the equity curve again.

Walk-forward research supports a **comprehensive bounded candidate grid** of up
to 48 configurations, including a subset of shared-ledger blends. Each training
window is chosen from already-completed historical data. Three chronological
unseen folds and a final sealed audit remain separate, and observed audit returns
are not used to rerank. Audit-only execution scenarios apply configured trading
assumptions, a two-session delay with at least 20 bps slippage, and a more
conservative two-session delay with at least 35 bps. Delays are in common market
sessions, **not a reliable 12-hour intraday execution guarantee**.

### Still not implemented

* Exhaustive combinatorial instrument optimization or point-in-time delisted
  stock coverage. Current historical prices can be affected by survivorship,
  corporate-action and data-source limitations.
* A full broker order book or intraday executable quote reconstruction;
  estimates use daily next-session opens and indicative spreads.
* Shared-ledger signed (margin/short) mixtures, interactive cash replay, or
  automatic execution of multi-sleeve blends in the live monitor.
* Independently trained predictive ML features or broker-verified future
  projections. Scenario resampling is hypothetical, not a calibrated forecast.
* Automatic selection using future or held-out audit results. Such selection
  would contaminate the audit and is intentionally prohibited.

Actual owner study inputs, chosen configurations, rankings, outputs and trades
remain in Git-ignored local private databases and must never enter public source.

### Saved blended research lifecycle

A qualifying multi-sleeve candidate can be imported from a completed private
universe tournament into the private version library. Its exact sleeve models,
weight percentages, position limits, execution delay, funding currency and cost
assumptions are saved as immutable model specifications. Historical custom-period
analysis uses `blended_portfolio_research.segment`, sharing cash and netting
orders exactly once; its equal-weight benchmark and delay stress use the same
instrument data and brokerage assumptions. Walk-forward optimization starts by
evaluating the immutable blend before comparing other compatible candidates.
Every run stores its output only in ignored private local databases.

The source inspector returns the actual Python blend allocation/backtest
functions. It refuses `simulation` and `live` contexts for these models
rather than substituting a different portfolio strategy. Research-only
versions cannot become paper or live deployments without a separate reviewed
engine implementation and explicit owner approval.

### Expanded training-only asset discovery and execution-robust ranking

The universe tournament can now opt into expanded basket search. It first
loads only genuine, quality-checked historical candles, then runs a bounded
greedy symbol screen across all eligible assets. Up to sixteen additional
distinct 6/8/12/16-asset baskets are proposed. The screen combines prior
126-session momentum, prior 100-session volatility, asset-class exposure
budgets, and pairwise past daily-return correlation. Every input is cut off
at the **earliest 60%-history training boundary across the available**
**instrument set**. This conservative cutoff is intentionally earlier than
the validation and final held-out periods of every evaluated candidate.
The result discloses the cutoff date, screened count, correlation-pool size,
and number of extra baskets. It is not a complete search of all subsets.

An optional execution-robust validation policy runs a second independent
validation-segment backtest per eligible model using second-session opening
execution and at least 20 bps modeled slippage. If the stressed model trips
a margin call, violates the configured validation drawdown limit, or cannot
trade, it is rejected. Otherwise it receives a **non-positive** additional
score adjustment equal to half the deterioration between the ordinary and
stressed validation-only objective scores. Stress results and the separate
score deduction appear alongside the candidate's normal ranking components.
The selected final historical 20% is never read by either the symbol screen
or validation execution penalty. Existing studies retain the original
focused/return-risk settings; new UI scans default to expanded/robust.

These checks reduce one type of lookahead leakage but cannot fix survivorship
bias, absence of delisted stocks, historical symbol changes, approximate
spread/slippage assumptions, overfitting from repeated human experiments,
or unsupported intraday liquidity and after-hours fills. The daily candle
model must not be interpreted as verifying executable orders within 12 hours.
