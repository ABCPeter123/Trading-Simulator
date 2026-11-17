# Trading Simulator contributor and agent instructions

**First read:** [docs/PRODUCT_VISION.md](docs/PRODUCT_VISION.md). It is the
project's canonical, enduring product context. Future changes must align with it.

**Mandatory strategy confidentiality:** Read
[docs/STRATEGY_PRIVACY.md](docs/STRATEGY_PRIVACY.md) before ANY coding,
Git commit, GitHub issue/PR, CI logging, data export, demo or deployment.
The engine implementation may be public; **the owner's real/generated/optimized
strategy rules, selected parameters, strategy versions, outputs, signals,
positions and actual trades must NEVER enter the public repository**, commit
messages, workflow artifacts, screenshots or shared demo. Use Git-ignored
local storage and independently synthetic examples only. Inspect every
staged change before committing, and never copy private trading logic into
a public fixture or documentation.

## Mandatory local-first / milestone-only release policy

**As of November 17, 2026, routine Vercel/Git deployment is frozen.**
Read [docs/LOCAL_FIRST_RELEASE_POLICY.md](docs/LOCAL_FIRST_RELEASE_POLICY.md).
Do not initiate Vercel deployments, promote builds, enable auto-deploy,
change deployment settings to bypass the freeze, or assume Git commits
should publish a website. `vercel.json` deliberately contains
`git.deploymentEnabled=false`. Work on local npm/Vite and loopback Python
first, validate in CI, and save code changes in GitHub without updating
any of the team's nine live Vercel sites. Only after a **major feature
milestone**, passing local regression/privacy checks, and explicit owner
approval may a single tested production release be published.

For local work: `.\start-local.ps1` launches Vite on 5173, Python on
8000 and the separate private portfolio research worker.
`.\start-local.ps1 -Mobile` exposes unauthenticated development UI
only to the same trusted LAN, never to the internet or a public tunnel.
`npm run verify:local` checks the production build offline. Preserve
the published website until an authorized release. This policy applies
alongside portfolio-first research and strategy confidentiality.

**Live website parity:** The actual production commit is pinned in
`config/production-baseline.json`, and the separate detached local preview
runs via `scripts/start-vercel-baseline.ps1` on port 5174. Main stays the
ongoing development source on port 5173, including unreleased improvements.
Never reset main to production, alter owner data, or deploy while performing
parity checks. See `docs/VERCEL_LOCAL_PARITY.md`.

## Mandatory portfolio-first research direction

**The product's trading strategy is a diversified portfolio of instruments,
not an isolated single-symbol strategy.** New research, model selection,
backtesting, risk and notification workflows must analyze cross-asset
allocations, shared cash, correlations, concentration, FX and asset-class
exposures. A single-asset study is a diagnostic or a backwards-compatible
subworkflow, not the system's default objective. Preserve historical data,
saved rules, filled orders, and the private/user-generated strategy boundary.

The initial USD portfolio model comparison is implemented in
`backend/portfolio_research.py`, shown in Strategy Discovery with separate
Performance, Allocation and Executions tabs. Future extensions need robust
CAD/USD conversion, fund look-through, explicit broker execution assumptions,
rolling walk-forward evaluation and cross-asset live deployment approval.
See [portfolio research](docs/PORTFOLIO_RESEARCH.md).

## Mission

Develop a personal, professional quantitative trading platform that:
- Builds, versions, backtests and stress-tests strategies using historical data.
- Evaluates out-of-sample performance and probabilistic future scenarios.
- Continuously monitors live market data through an engine that runs independently
  of the website, with daily or similar low-frequency decision cadence.
- Produces reviewable, risk-checked trade recommendations and sends notifications.
- Lets the user manually place broker trades, then confirm/edit the recorded fills.
- Persistently tracks live positions, performance, strategy health, prediction
  quality, failures, critical alerts, and all audit history.
- Prioritizes capital preservation and risk-adjusted returns. Never promise profit.

The project is **not** primarily a game, a high-frequency trading app, or a
historical simulator with no live deployment path. The current code does not
yet implement all of the above. Distinguish implemented functionality from
future requirements in every change summary.

## Nonnegotiable product principles

1. **Human-in-the-loop execution is the default.** A signal is never the same
   as a broker fill. Do not automate real trades without explicit approval.
2. **Risk first.** Model downside risk, slippage, drawdown, fees, concentrations,
   exposure, borrowing and margin risks where relevant; include circuit breakers.
3. **24/7 engine, not 24/7 browser.** Persist jobs, events, strategy versions,
   alerts, acknowledgments and fills. Design for recovery and idempotency.
4. **Research integrity.** No future-price leakage, fake historical candles,
   silent graph truncation, in-sample-only optimization or guaranteed forecasts.
5. **Clear daily operator UX.** Prefer Dashboard, Strategy Lab, Backtests &
   Forecasts, Live Strategy Machine, Portfolio & Trade Journal, Alerts & Health.
   Preserve existing functionality and use nested navigation rather than
   placing every control on a single page.
6. **Private is private.** The public demo and owner's live/local portfolio
   remain fully isolated. Secure any future real-data hosted service.
7. **English and Simplified Chinese; desktop and mobile feature parity.**
   Consistent terminology; no gamified arcade metaphors.
8. **Auditability.** Save decisions, strategy versions, data sources and
   timestamps; user corrections to actual fills must preserve revision history.
9. **Manual execution delay.** Recommendations should remain actionable through
   a clearly validated intraday or same-day window, rather than assuming
   millisecond execution.
10. **Test before declaring success.** Preserve prior sessions, test migrations,
    chart coverage, core risk constraints and alert deduplication/recovery.

Implement changes incrementally without deleting saved simulator or strategy
features. Refer back to the detailed requirements and phases in PRODUCT_VISION.md
before architectural redesigns.

## Current implementation checkpoint

See [docs/LIVE_MACHINE.md](docs/LIVE_MACHINE.md) for the private daily
strategy worker, historical candidate optimizer, signal queue, notifications,
manually confirmed fills, execution attribution and explicit limitations.
`backend/live_machine.py`, `backend/research_optimizer.py`,
`backend/live_notifications.py` and `backend/live_routes.py` are the
local beta workflow, not a brokerage automation system. The Windows
`start-live-machine.ps1` worker runs independently of the website.

Continue toward the full vision, including full walk-forward/regime testing,
risk controls for leverage, short sales and hedging, broker statement
reconciliation and audited live model drift. Do not label beta components
production-safe or claim that stable profits can be guaranteed. Every new
implementation must preserve the public-source/private-generated-strategy
boundary and add tests using independently synthetic fixtures.

