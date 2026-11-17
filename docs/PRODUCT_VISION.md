# Trading Simulator: Product Vision and System Requirements

**Status:** Canonical product goal and long-term requirements, recorded 2026-11-17.
**Audience:** All future contributors, coding agents, UI/design agents, and project discussions.
**Product name:** Trading Simulator. Keep a professional, finance-oriented interface.

**Permanent privacy requirement (2026-11-17):** The trading engine and UI
source code can be public, but the owner's **actual learned/generated,
optimized, selected or deployed strategies and their parameter values must
remain confidential**. Keep strategy versions, research output, signals,
models, trades and performance records in private Git-ignored storage.
Never leak these through public commits, GitHub Actions, examples, screenshots,
logs, issue bodies or a public demo. See [Strategy Privacy Policy](STRATEGY_PRIVACY.md).
This rule applies to all future work, especially AI strategy generation,
backtesting, trading, notifications and live deployment.

> **This is the product specification, not a statement that these features are already implemented.**
> The repository began as a historical simulator. The intended product is a continuously running
> personal quantitative trading research, live signal, and human-approved execution platform.

## 1. North-star objective

Build an end-to-end trading decision platform that helps its owner:

1. Develop and save rules-based and model-assisted strategies.
2. Train and evaluate strategies on high-quality historical market data without look-ahead leakage.
3. Understand why and when each strategy trades, including behavior in different market regimes.
4. Compare strategies using risk-adjusted outcomes, stability, transaction costs, drawdown, and stress tests.
5. Use probabilistic future scenarios, forecasts, and uncertainty estimates to test how a strategy
   *might* behave. Predictions must never be represented as guaranteed outcomes.
6. Promote a sufficiently validated strategy from research to paper trading, then to live market monitoring.
7. Run an always-on, resilient signal engine that checks current market conditions and generates actions.
8. Notify the owner when an action is due. The owner normally executes through a broker manually,
   possibly later in the **same trading day**, and confirms or edits the resulting trade in this platform.
9. Persist, monitor, reconcile, and analyze every recommendation, decision, execution, position,
   strategy revision, risk change, and alert.
10. Continually assess live performance and provide controlled feedback for strategy improvement.

**Risk objective:** Seek strong, repeatable *risk-adjusted* returns within user-defined small-risk
limits. Avoid maximizing gross profits at the expense of capital preservation. There is no way
to guarantee consistent profits or low losses; show uncertainty and failure cases explicitly.

**Horizon:** Low-to-moderate-frequency investing/trading. The user expects roughly daily decisions
and is not pursuing high-frequency execution, ultra-low-latency market making, or microsecond fills.
Signals should include a validity window, preferably a clearly justified same-day execution window.

## 2. Guiding principles

- **Research -> validation -> deployment -> signal -> human execution -> monitoring -> improvement**
  is the central workflow. Every primary screen should support one of these steps.
- A trading *signal* is not a *broker execution*. Never mark a proposal as filled until the user
  confirms the broker order and its actual execution details.
- Full automation means automated market watching, analysis, signals, notification, monitoring,
  reporting, and failsafes. **Human approval/execution remains the default.**
- A historical simulation, paper-trading state, and live position record are separate ledgers.
  They must never mutate one another or appear as a single brokerage account.
- Keep complete original data and complete historical audit trails. Visible chart ranges are
  viewports, not destructive truncation.
- Maintain explicit run state and provenance: draft, backtested, walk-forward tested, paper,
  live-monitoring, paused, retired. A strategy cannot silently become live.
- Make risks, uncertainty, data freshness, stale signals, model drift, and missing market data visible.
- Preserve the whole functionality set when refactoring UI. Keep English and Simplified Chinese parity,
  mobile and desktop feature parity, and existing saved sessions.
- Professional terminology and calm, readable UI. No arcade, XP, leaderboards, badges, or other
  gamification in the intended product experience.
- Model execution realistically, including delays, non-fills, fees, spread/slippage, dividends,
  corporate actions, interest, overnight gaps, borrow availability, short borrow fees,
  margin requirements, and leverage where relevant.
- Keep personal/private live trading data and credentials isolated from any public demo URL.
  Public visitors must not access private positions or local/paid AI services.

## 3. Target operator workflow

### A. Strategy Lab: author and refine

- Visual strategy builder plus advanced DSL/configurable code, with accessible documentation.
- Strategy categories: momentum/trend, mean reversion, statistical signals, portfolio allocation,
  hedging, volatility/risk control, and predictive-model-enhanced rules.
- Adjustable asset universe, sizing, entries, exits, rebalance cadence, order types,
  stop loss, take profit, time-based exits, exposure and liquidity constraints.
- Shorting, leverage, margin, hedges, and correlated exposure analysis as **explicit optional**
  capabilities, each with conservative risk caps, clear costs, and suitability warnings.
- Named, versioned strategy library; compare alternatives, checkpoint experiments,
  fork variants, and reproduce any run with saved configuration and data snapshot.
- Show the deployed version and draft version separately to prevent accidental live changes.

### B. Historical research and performance diagnostics

- Long daily price histories where available, with correct timestamps, corporate actions,
  adjusted/unadjusted price conventions and source coverage.
- Backtests with no future leakage. Realistic next-action execution, latency assumptions,
  fees, spread/slippage, turnover, liquidity constraints, and portfolio cash accounting.
- Train/validation/test partitioning; rolling and walk-forward out-of-sample tests;
  benchmark comparisons; parameter sensitivity and robustness checks.
- In-depth event-level inspection: every signal, rule evaluation, trade rationale,
  proposed/actual size, exposure, return attribution, fees, hedge impact, and P&L.
- Analyze behavior in bull/bear/sideways markets, drawdowns, recessions/shocks,
  high/low volatility, rate changes, large market gaps, and correlated selloffs.
- Report total/annualized return, volatility, Sharpe/Sortino when meaningful, max drawdown,
  recovery time, Calmar, turnover, average holding time, win/loss distributions,
  downside tail risk, risk budget consumption, and parameter stability.
- Historical replay can move backward and forward without leaking future information.
  Preserve the full dataset in charts and show only the requested viewport.

### C. Forward-looking research

- Models that estimate scenario distributions, risk bands and probabilistic outcomes.
- Evaluate calibration, prediction quality, baseline comparisons, regime sensitivity,
  model drift, and forecast error using genuinely unseen periods.
- Monte Carlo/bootstrap/stress scenarios should cover fat tails and regime changes where feasible,
  not rely on a single optimistic path or present probability as certainty.
- Clearly distinguish *historical observations*, *hypothetical simulations*, and *live predictions*.
- Forecasts inform risk decisions and strategy comparison; they do not override hard risk limits.

### D. Deployment and continuous live monitoring

- Explicit deployment pipeline: backtest -> out-of-sample -> paper forward test ->
  live-monitoring approval. Include a reviewed release/version and deployment timestamp.
- Reliable 24/7 service running independently of the browser being open. The engine should
  resume after restart with durable state, idempotent jobs, retries, scheduler/market calendars,
  clock/time-zone discipline, health checks, and failure alerts.
- Daily (or other user-selected low-frequency) evaluation on latest *fresh enough* market data.
  Consider session close, overnight behavior and end-of-day execution windows.
- Show a **Live Strategy Machine** view: active version, tick/check history, next planned
  evaluation, health status, sources and data freshness, latest rule evaluations,
  pending signals, suggested orders, expiry windows, and reasons for no action.
- Deduplicate routine signals. Re-evaluate when data meaningfully changes without repeatedly
  creating duplicate recommendations.
- A generated recommendation records: strategy version, instrument, side, proposed units/notional,
  estimated allocation/exposure, rationale, timestamp, evidence, model confidence if available,
  risk checks, urgency, expiry, and status.
- By default, **do not place real brokerage orders automatically**. Even if broker integration is
  added later, it requires a separate explicit permission and a hard kill switch.

### E. Notifications and acknowledgments

- Send actionable trading signals and operational alerts via a convenient channel.
- Priority candidates: Discord webhook (fast setup), email, and optional SMS/iMessage through
  a supported transport. Do not depend on iMessage integration for the MVP.
- Signal alerts: buy/sell/trim/hedge instructions, intended action window, reason,
  latest data timestamp, size, risk, and a deep link to the corresponding record.
- Routine alerts are deduplicated and can be batched.
- **Critical** alerts (risk limit breach, stale feed, halted engine, persistent data error,
  unacknowledged urgent signal, unexpected exposure or failed reconciliation) can repeat
  aggressively **until acknowledgment or resolution**, with configurable escalation.
  Avoid infinite uncontrolled spam or sending credentials/private account details.
- Provide notification history, delivery outcomes, retry status, quiet-hour rules for
  noncritical messages, acknowledgments, and a tested fallback channel.
- A same-day trade suggestion must explicitly indicate whether it is still valid based
  on time, market data freshness and changing market conditions.

### F. Human execution and permanent trade ledger

- After an alert, the owner executes in their external broker and records what actually happened.
- One-click **Record execution** starts from the suggested order and prefills all known fields.
  Every field remains editable: asset, account, buy/sell, quantity, order type,
  order/average fill price, execution timestamp, fees, FX, currency, notes, and broker reference.
- Track proposed / acknowledged / submitted externally / partially filled / filled /
  skipped / expired / canceled states. Support split and partial fills, manual overrides
  and reasons for not following recommendations.
- Persist historical trade records permanently and reconcile lots, holdings, cash flows,
  realized/unrealized P&L, borrow/financing costs and dividends.
- Corrections must leave an auditable revision history, not silently erase the old fill.
  Add optional CSV import/export and broker statement reconciliation later.
- Distinguish hypothetical portfolio curves from the user's actual, confirmed live performance.

### G. Ongoing portfolio and strategy health

- Primary dashboard: account/portfolio value, cash, gross/net exposure, leverage,
  active strategies, open positions, pending human actions, outstanding alerts,
  daily/period returns, drawdown, P&L and benchmark comparisons.
- A monitoring page should show live engine heartbeat, last and next evaluation,
  data providers, missing data, execution divergence, alert queue, diagnostics,
  backtest-vs-live drift, and expected/realized behavior.
- Strategy attribution by instrument, regime, entry/exit rationale, costs, risk,
  forecast quality and deviations from intended fills.
- Controlled tuning process: detect degradation, suggest changes, run revalidation
  and paper shadow tests, then require explicit approval to deploy a new version.
  Do not allow models to silently self-optimize using live future observations.
- Safety guardrails: maximum drawdown, per-trade risk, exposure by issuer/sector/factor,
  correlated positions, max leverage, margin utilization, concentration, loss limits,
  failed-data checks, kill switch, paused mode, circuit breakers, risk alerts, and
  explicit restoration procedures.

## 4. Product navigation: design target, not existing implementation

Avoid showing all controls in one dense page. Make the common operator workflow
unmissable. Proposed high-level tabs:

1. **Dashboard**: Today's status, action-required cards, pending trade confirmations,
   risk, portfolio P&L, warnings, strategy/engine heartbeat.
2. **Strategy Lab**: Build, compare, version, tune, and validate strategies.
3. **Backtesting & Forecasts**: Historical replay, scenario/regime breakdown,
   forecast distributions, strategy diagnostics and chart annotations.
4. **Live Strategy Machine**: Deployed rule set, current live evaluations,
   upcoming checks, new/pending/expired signals, monitoring and pause controls.
5. **Portfolio & Trade Journal**: Positions, actual executions, suggested-vs-filled
   actions, manual edits and corrections, realized results and exports.
6. **Alerts & System Health**: Notification channels, urgency/escalation,
   data quality, failures, automated job status and safety guardrails.

Use nested tabs/panels for specialist features, with progressive disclosure.
Core operations (check signal, record trade, acknowledge alert, inspect exposure,
pause machine) should be one or two clear actions from the dashboard.
Keep a usable phone view with the *same* important capabilities as desktop.
Maintain consistent timeframes, chart rendering, and en/zh translations.

## 5. Safety, architecture, and reliability requirements

- Research engine and live engine share strategy semantics but have separate,
  traceable data inputs and immutable model/strategy versions.
- The engine must run independently of any active browser session; use durable
  schedules/jobs, structured logs, event store, persistent signal queue and
  retry/backoff with idempotency keys.
- Treat data freshness, exchange hours and corporate actions as first-class
  validity conditions for new signals.
- Protect production access with authentication and authorization, TLS, secrets
  handling and appropriate API throttling before any real portfolio or broker
  information goes online.
- Never connect a public demo tunnel to the private live accounts, trading logs,
  saved strategies, credentials or notification configurations.
- Add unit, integration, simulated replay, fault-injection and recovery tests.
  Validate that failures default to **no fresh signal** rather than silently
  trading on missing/stale/corrupt data.
- Audit all state changes and notifications, including the source/strategy/data
  version, actor, timestamp and reason.
- No guarantee of continuous profitability, accuracy, or uninterrupted operation.
  Use conservative constraints and transparent reporting rather than claims of
  guaranteed returns or "risk-free" strategies.

## 6. Development roadmap

**Phase 1: UX and data foundations.**
Reorganize the interface around the six operator workflows. Preserve all
existing capabilities and historic saves. Standardize en/zh copy, charts,
asset/time filters and table responsiveness. Define a canonical data model
for strategy versions, signals, user confirmations, executions and account states.

**Phase 2: Strategy research and evaluation quality.**
Improve historical data ingestion and corporate action handling, reproducible
backtests, walk-forward tests, realistic fees/slippage/borrow costs,
scenario/regime diagnostics, risk analytics and portfolio comparisons.
Do not label a strategy "best" on in-sample returns alone.

**Phase 3: Durable live paper signal engine.**
Introduce an independent always-on scheduler, saved deployments,
live-data checks, evidence-backed daily recommendations, Discord/email
alerts, acknowledgments, critical monitoring, risk limits and manual
trade-confirmation workflows. Start with shadow/paper signals before live capital.

**Phase 4: Real portfolio operations.**
Actual execution journal, corrections, positions, cash and P&L reconciliation,
fill-vs-recommendation tracking, drift detection, operational dashboard,
backup/recovery and private authenticated deployment.

**Phase 5: Advanced risk and optional execution integrations.**
Robust support for shorting, leverage, margin, hedges and portfolio risk;
expanded risk forecasts, broker imports, optionally carefully permissioned
broker integrations. Automatic real order placement is *not* in the default
scope and requires explicit authorization and extensive safeguards.

At every phase, improve actual usability, preserve past records and prove
functionality with automated tests. Prefer end-to-end operator value over
isolated UI decorations or proliferation of unrelated features.

## 7. Existing features versus intended future features

**Implemented research capabilities:** historical single-asset
and multi-asset replay, simulated orders, chart indicators and strategy rules,
saved private strategy versions, performance analytics, stochastic scenarios,
bilingual desktop/mobile workspace, a separate paper ledger, and local AI.
Private Strategy Discovery now runs chronological training/validation/held-out
tests across a small parameter grid. Candidate selection results stay in
local Git-ignored SQLite.

**Implemented private operations beta:** a browser-independent, persistent
local Python worker for previous-day live market checks, versioned paper or
human-execution monitoring deployments, idempotent recommendation records,
risk-based allocation and realized-loss stops, critical Discord/email alert
delivery, manual trade confirmations, audited corrections, currency-separated
realized results and actual-versus-suggested fill deviation reports.
The worker is only available while the owner's computer runs.

**Still not production-ready:** guaranteed unattended 24/7 availability,
validated market calendars and reliable professional live feeds, full
multi-account reconciliation, automated brokerage execution, maintained
short/margin/leverage and hedge accounting, advanced multi-asset risk
constraints, full walk-forward/drift evaluation and automated incident
recovery when the host itself is offline. These are enduring requirements,
not claims of current functionality. See [LIVE_MACHINE.md](LIVE_MACHINE.md).

## 8. How future chats and contributors should use this file

When continuing work on Trading Simulator, read **this file first**.
Interpret ambiguous user requests in light of the goal: personal, professional,
risk-aware, semi-automated live trading research and monitoring. Do not
reintroduce gamification, treat the toy historical simulator as the end goal,
or prioritize low-latency HFT features. Propose or implement changes that
advance the workflow from research to durable live signals to confirmed
real-world trade tracking. Ask only when an irreversible deployment or live
broker/notification action requires owner-specific authorization.
