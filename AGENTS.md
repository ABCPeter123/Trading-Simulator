# Trading Simulator contributor and agent instructions

**First read:** [docs/PRODUCT_VISION.md](docs/PRODUCT_VISION.md). It is the
project's canonical, enduring product context. Future changes must align with it.

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
