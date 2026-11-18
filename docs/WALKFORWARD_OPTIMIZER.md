# Private rolling walk-forward optimizer

This Research Lab feature advances the previous high-performance discovery mode
without claiming that 50–60% CAGR or a Sharpe ratio of 2.0 is achievable.

## Operation

Within **Strategy Tournament**, open one ranked strategy and expand
**Walk-forward optimization and unseen-period audit**.

The selected strategy contributes a **fixed basket of actual historical assets**.
For that basket, the optimizer tests a bounded public grid of model families and
allocation limits, with user-selectable risk objectives and execution assumptions.

Four expanding training windows end at approximately 50%, 60%, 70% and 80%
of the shared trading-day history. At each boundary, the optimizer:

1. Executes each candidate's historical training simulation entirely before
   the boundary, using the same completed-candle and opening-fill assumptions
   as the existing research engine.
2. Chooses an eligible model/parameter configuration based solely on that
   training history, including transaction costs and maximum-drawdown limits.
3. Tests that frozen choice on the *subsequent* unseen shared-session block,
   without feeding those prices into training or changing the choice.
4. Repeats the process independently with an expanded training window.

The first three out-of-sample blocks end at 80% of historical observations.
The fourth selection is trained on the prior 80% and evaluated once on the
sealed final 20%. The audit has at least 126 sessions or no audit is produced.
There must also be at least 90 post-warmup initial training sessions and at
least 30 sessions in each subsequent test block.

The selected portfolio is **not continuously executed between blocks**.
Each test starts with virtual $100,000 and zero holdings. The displayed
walk-forward curve stitches *returns* into a normalized index, not a real
rolling account or carry-forward position ledger. Costs on the first trade
of every segment are explicitly modeled.

## Optimization scope

The optimizer searches at most 12 or 24 deterministic configurations.
For standard and other long-only models it compares compatible allocation
families and varying position caps, invested-capital targets, equity-category
limits and redistribution choices. Signed research-only models search
compatible synthetic borrowing/short models and position caps only.
All historical candidates use the selected basket and configured daily
execution-delay setting. No basket selection, AI-generated indicators,
unlimited hyperparameter search or broker execution is included.

A candidate is excluded from training selection if it lacks meaningful
trades, has inadequate exposure or exceeds the configured maximum drawdown,
or triggers a synthetic margin call. The held-out audit never changes
selection. A slower-fill, higher-slippage audit stress run is reported too.

For context only, a one-sided Gaussian-i.i.d. approximation for the
walk-forward excess Sharpe is shown with a Bonferroni trial-count multiplier.
This is **not** robust inference, Deflated Sharpe, PBO, or proof of an edge.
The approximate p-value assumes independent stationary Gaussian daily
returns and ignores autocorrelation, market regime drift, and user-driven
repeat research. Repeated manual tuning after viewing an audit invalidates
its claim to being an untouched test.

## Additional pre-audit selection-bias diagnostics

The optimizer now replays every runnable candidate on the **pre-audit 80%
only**, before executing the final audit. The private output contains
aggregate estimates, not the private candidate curves or selected rules:

- **Estimated Deflated Sharpe probability**: compares the selected candidate's
  pre-audit net daily Sharpe with a null maximum across the attempted trial
  count. The threshold uses the expected maximum of independent normal
  Sharpe estimates, with a conservative floor for null dispersion.
  The estimated probability includes daily skew/kurtosis moment terms.
  All historical Sharpe calculations apply the explicitly assumed cash rate.
- **CSCV estimate of Probability of Backtest Overfitting (PBO)**: divides the
  *same pre-audit* candidate return curves into eight sequential blocks,
  evaluates 70 complementary four-block splits, and counts the fraction
  in which the winning in-sample candidate ranks below the out-of-sample
  median. Identical return paths count as one candidate. Unidentifiable or
  insufficient histories produce N/A rather than fabricated scores.

These are **statistical approximations**, not certified DSR/PBO confidence.
CSCV is combinatorial and nonchronological, not a tradable rolling
walk-forward simulation. Returns are serially correlated, strategies share
market exposures, and manual researcher trial counts may be unknown. The
pre-audit diagnostic can also be influenced by the earlier walk-forward
model search conducted on that same history. Consequently, a strong score
does not validate a future return forecast. The separate final held-out
audit remains untouched by either diagnostic, and forward-paper monitoring
is still necessary.

## Privacy and limits

All real market-archive inputs, selected private parameter values, risk reports,
equity curves and job details remain in the local Git-ignored
`data/walkforward_research.sqlite3`. The public GitHub repository contains
only reusable engine code and independently synthetic fixtures.

Provider-data availability and common-session alignment constrain each study.
No synthetic fallback prices fill missing actual market history. FX uses the
previous completed FX observation. Margin, borrow availability, taxes,
corporate-action and dividend treatment remain approximate. Historical
survivorship bias is not resolved by walk-forward alone.

The research process sends no broker orders. Reports can inform paper
forward testing, but do not automatically create deployed strategies.

## Evidence integrity diagnostics added after the original audit

The private report now includes a **pre-audit-only cash and execution-cost
counterfactual** for each fold's training window and for the final selection's
training window. It compares the selected model with configured costs, the
same model with zero transaction costs, and constrained equal weight with
configured costs. Training sessions, turnover, gross exposure and fees appear
alongside returns. The zero-cost rerun can alter integer share quantities, so
its return difference is a sensitivity, **not exact causal fee attribution**.
Cash holdings and category limits may protect against drawdown; a return gap
alone does not justify increasing investment. These comparisons do not score,
reselect or rank models.

Each completed study also stores a **historical input provenance check**:
source, date range, mismatched calendars, adjustment metadata where explicitly
provided, and previous-completed-day FX handling. The default Yahoo request
uses `auto_adjust=False`; archived provider OHLC does not preserve a certified
total-return adjustment record. Delisted-security histories, historical index
constituents, dividends, splits and issuer-level corporate actions are not
verified by this check. The report labels those limitations rather than
claiming a survivorship-free backtest.

See [forward-paper monitoring](FORWARD_PAPER.md) for the independently
frozen exact-session price-only control on newly observed sessions.
Reviewing any previously unsealed audit disqualifies those same dates
from being described as fresh evidence after subsequent research changes.
