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
  session uniqueness, preventing duplicate fills on restart. If more than one
  completed trading session arrives between successful checkpoints, the study
  pauses without recreating trades at historical opens. Start a fresh study
  instead of claiming this as continuous forward-paper evidence.
- A descriptive comparison against the previously sealed historical audit.
  A forward Sharpe or CAGR from fewer than 30 new sessions is not used to
  report a historical-vs-forward drift comparison.

## Broker-aware scenario profiles (November 18, 2026)

Forward-paper studies may now freeze a Wealthsimple, Interactive Brokers
Canada, or legacy generic cost scenario. Profiles expose a simulated
cash/margin account, account funding currency, optional financing and
borrow-rate overrides, slippage, an additional FX spread, and the choice
of a later daily open or later daily close for a hypothetical fill.

- **Wealthsimple**: USD stock commission is modeled as zero, USD margin
  financing uses an indicative CAD-equivalent aggregate borrowing tier.
  Source: https://help.wealthsimple.com/hc/en-ca/articles/33646742423195-Learn-about-fees-and-interest-in-a-margin-account
  Share shorting is not supported, so paper strategies needing short
  shares are rejected for this broker profile.
  Source: https://help.wealthsimple.com/hc/en-ca/articles/33646380604187-Trade-options-in-a-margin-account
- **IBKR Canada**: illustrative U.S. tiered share fees use $0.0035/share,
  $0.35/order minimum, capped at 1% of notional (external venue/regulatory
  charges omitted). Indicative initial USD borrowing rate is 5.13% for
  the first $100,000, but this simplified profile does not calculate
  IBKR's blended marginal tiers automatically; users can override it.
  Sources: https://www.interactivebrokers.ca/en/index.php?f=49637 and
  https://www.interactivebrokers.ca/en/index.php?f=46803
  A short-stock model requires an explicit **unverified borrow
  assumption**. IBKR stock-loan inventory and rates change during the
  day; this engine neither checks actual locates nor submits orders.
  Source: https://www.interactivebrokers.ca/en/trading/short-securities-availability.php
- **CAD funding**: A CAD-denominated paper starting amount converts
  *once* into a simulated USD account at the previous completed
  USD/CAD close, after an illustrative conversion cost. Wealthsimple
  funded USD account conversion uses its published CAD amount tiers:
  1.5% below $10,000; 1% below $25,000; 0.5% below $100,000;
  0% at and above $100,000. A variable corporate FX spread is not known.
  IBKR manual spot conversion uses 0.20 basis points with $2 USD minimum.
  Sources: https://help.wealthsimple.com/hc/en-ca/articles/4415548242971-Convert-funds-between-CAD-and-USD
  and https://www.interactivebrokers.ca/en/pricing/commissions-spot-currencies.php
  The USD ledger is later marked in CAD using **prior completed** FX
  closes, and CAD-funded studies apply the drawdown stop to their CAD
  marked value. No CAD stock trading or dual-currency margin collateral
  ledger is implied.

The current profile is **not** a live broker integration. It does not
know the user's account tier, holdings at other brokers, borrow locates,
executable currency prices, product-specific margin requirements, exchange
holidays, or full regulatory charges. Assumptions are frozen per study,
and each alternate broker scenario gets an independent private paper
ledger. The date is the reference date for the assumptions, not a live
market-data refresh or an ongoing pricing guarantee.

**Execution interval constraint**: After a U.S. market-close signal at
4:00 pm ET, the following regular opening print is approximately 17.5
hours later, before weekends/holidays. A promised under-12-hour
completion cannot be inferred from daily bars; selecting the next
session's close is an adverse/slower execution scenario, not an
intraday time-window forecast. Activation timestamps are checked
against the modeled 9:30 am opening and 4:00 pm closing auctions. A study
started after an auction cannot retroactively fill at that auction; it
waits for a later eligible session instead.

## Deliberate limitations

- **Not live trading and not real broker paper orders.** Processing an
  observed daily bar later reconstructs a hypothetical fill at its open;
  it does not prove an order could have been placed, located or filled at
  that price. There is no direct broker connection.
- USD *instruments* only. CAD may fund a separately modeled USD paper
  subaccount, but CAD share orders, margin collateral across currencies,
  and CAD/USD automatic conversion on each sale are not reproduced.
  The historical multi-currency engine remains unchanged.
- Brokerage commissions follow the selected approximate cost profile;
  spread/slippage remain embedded in simulated fill prices. Financing
  and borrow rates are editable research assumptions. No actual stock-loan
  locate, dividend/corporate-action ledger, true margin collateral or
  tax modeling is supplied.
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
