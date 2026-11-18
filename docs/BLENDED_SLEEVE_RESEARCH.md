# Shared-cash portfolio sleeves and annual consistency diagnostics

This milestone extends the private rolling walk-forward optimizer beyond
choosing one allocation model for one fixed asset basket.

## What is implemented

The candidate generator now includes bounded two- and three-model **long-only
strategy blends**. Some combine relative momentum, trend filtering,
inverse-volatility sizing, defensive rotation, or diversified risk parity.
The component models produce actual per-symbol target allocations from
prior-session observations. Their weighted allocations are combined before
any trade, with one common cash ledger, one net trade per symbol per rebalance
and one set of bid-ask, slippage, commission and currency-conversion fees.

The executable allocation is constrained by a user-selected gross exposure
target, the final maximum per-instrument weight and applicable asset-class
exposure limits. Optional redistribution cannot buy an asset unselected by
every component or violate the final limits. Zero-eligible-signal periods
remain cash. Short selling and margin borrowing are never allowed inside
the long-only shared-cash blend. They remain separate, research-only
signed-exposure models with their original assumptions.

For the untouched final audit, the system also compares three prior-selected
candidates: highest training CAGR, highest training excess Sharpe and the
balanced risk-adjusted objective. All three configurations are frozen using
pre-audit history, and the audit never elects a new candidate. These are
diagnostic comparisons, not three independent forward-tested strategies.

Blend selection uses exactly the same expanding-window, prior-only objective
ranking as single models. The final 20% held-out audit is not an input to
candidate construction or selection. The bounded focused search retains 12
configurations, while the extended search retains 24. Searches cannot be
described as exhaustive across every asset or every parameter.

## Annual consistency

Additional diagnostics report:
- Worst observed rolling **252-trading-session** return
- Percentage of overlapping rolling windows that achieved the *configured*
  CAGR goal (descriptive, not an independent trial success rate)
- Per-calendar-year observations, with partial years explicitly marked
- Worst observed complete calendar-year return, **only** for calendar years
  with at least 200 sessions, a January first session by the 15th and
  a December final session from the 15th onward

Short audit windows expose null annual figures instead of extrapolating a
worst calendar year. The historical equity curve may represent separately
reset fold returns; the resulting stitched index is not a continuous funded
portfolio with carried holdings. No confidence interval, probability of
meeting annual targets, or guarantee is implied.

All generated positions, candidate settings, results, trade logs and performance
tables stay in the owner's private ignored SQLite research data. Public GitHub
source includes generic algorithms and independently generated synthetic tests.

## Remaining work

The blend search is bounded and starts from the user-selected fixed basket.
The research does not yet optimize fully unrestricted baskets, sector lookthrough,
hedge ratios, short borrowing inside a single signed shared ledger, dynamically
selected rebalance periods, option strategies or genuine portfolio-forward-paper
tracking. Complete corporate-action, dividend, tax and point-in-time universe
data are still outstanding before relying on live performance comparisons.
