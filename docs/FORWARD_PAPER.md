# Forward-paper monitoring (private local research)

A completed walk-forward report now has an explicit **Start forward paper**
action. The frozen pre-audit-selected portfolio is copied into an independent
simulation-only SQLite ledger in `data/paper_forward.sqlite3`. A finished
historical study is not automatically promoted to paper or live trading.

## Operation

1. Start the local Python backend and private research worker, then run a
   walk-forward study in Research Lab. The selected model and actual asset
   basket remain private and are not committed.
2. Open the completed study and select **Start forward paper**. Activation
   requires currently fresh, synchronized, real completed daily OHLC bars for
   each member of the frozen basket. It starts from the latest completed
   session with virtual cash and zero positions. **No earlier history is
   backfilled into the forward ledger.**
3. Keep `start-live-machine.ps1` running to perform incremental processing
   independent of the browser, or use the **Check newly completed sessions**
   button. New daily provider observations are deliberately held until the
   following calendar day; fill prices use the subsequently observed opening
   price with modeled spread and slippage.
4. Review the portfolio in **Live Strategy Machine > Forward-paper
   monitoring**, including equity, USD cash, net drawdown, total gross
   exposure, simulated fills, financing charges, and performance drift.
   All paper orders are simulated. They do not touch the actual trade journal.
5. A study can be paused or retired. Pause ends continuous collection
   permanently, to avoid claiming that missing sessions were paper-forward
   observations. Starting a new study creates a new baseline.

## Supported scope

- Frozen walk-forward selections on two to sixteen USD-denominated,
  tradable U.S. stocks/ETFs with aligned provider history.
- Individual standard portfolio models, advanced hedged and experimental
  signed-margin models, and the long-only shared-cash blended sleeves.
- Fixed 21-session rebalancing cadence; lag of one or two common sessions
  from completed-close signal to later observed-open hypothetical fill.
- Signed share holdings, shared cash, spread and 8-basis-point slippage,
  long-only no-borrow constraints, indicative flat annual financing and
  borrow rates, maintenance floor and configurable maximum drawdown stop.
- State, marks, and fills committed to durable SQLite using transactions and
  session uniqueness, preventing duplicate fills on restart.
- A descriptive comparison against the previously sealed historical audit.
  A forward Sharpe or CAGR from fewer than 30 new sessions is not used to
  report a historical-vs-forward drift comparison.

## Deliberate limitations

- **Not live trading and not real broker paper orders.** Processing an
  observed daily bar later reconstructs a hypothetical fill at its open;
  it does not prove an order could have been placed, located or filled at
  that price. There is no direct broker connection.
- USD instruments only, no FX conversion or CAD/foreign account aggregation
  in this milestone. This does not change the historical multi-currency engine.
- Commissions are assumed zero; spread/slippage are embedded in simulated
  execution prices. Financing and borrow rates are fixed research assumptions
  and do not represent a verified brokerage rate. No actual stock-loan locate,
  dividend/corporate-action ledger, margin collateral or tax modeling.
- Missing, stale, cached, demo or unsynchronized daily bars prevent advancing
  the private paper ledger. Feed errors appear on the dashboard and do not
  fabricate portfolio returns.
- Because daily signals use a 21-session cadence and fills are hypothetical
  at later observed opens, intraday fill uncertainty remains significant.
- Historical audit CAGR, paper annualization and estimated Sharpe are not
  evidence of reaching a 50–60% annual return objective. The paper sample
  begins only at activation and is initially statistically very small.
- Vercel deployments stay frozen. No changes here publish a site, submit
  real orders, alter saved strategies, or touch the actual broker journal.
