# Professional Workspace and Replay Time Navigation

The original Trading Terminal and both historical simulators now organize
existing tools into **tabs**. All charting, analytics, orders, automation,
risk controls, trade journals, strategy validation and data import features
remain available, but the page no longer displays everything simultaneously.

## Workspace tabs

The two historical simulator modes share six sections:

| Tab | Contents |
| --- | --- |
| **Market Overview** | Real revealed candles, SMA overlays, volume, historical timeline, crossovers and current metrics |
| **Orders & Positions** | Order ticket, positions, pending orders, stop-loss, take-profit and sizing |
| **Strategy & AI** | Editable strategy DSL, rule templates, safe visual rule builder (single-asset), AI research assistant |
| **Performance Analytics** | Equity against benchmark, drawdown, fees, capital exposure, rolling returns and full exportable audits |
| **Scenario Research** | 256-path GBM scenarios, hypothetical probability bands and Black-Scholes theoretical option calculator |
| **Trade History** | Historic fills, trade journal and operation events |

The original Trading Terminal uses three tabs: **Market & Charts**,
**Account & Orders** and **Backtest Research**. No existing item is removed.

Visible gamification elements (level, points, XP and achievement badges)
are hidden from the interface. Their original saved data remains in the
backend for backward compatibility; financial state and calculations are
unchanged. Labels now use professional research terminology rather than
game-style seasons and ranks.

English and Simplified Chinese remain supported.

## Going backward in historical replay

Both single-asset and portfolio simulators record exact checkpoints
at every observed replay step, including positions, account balances,
risk settings, strategy, queued orders, fill-count boundaries and
equity-curve boundaries.

The timeline provides:

- **Previous step**: inspect an earlier *saved* historical checkpoint
- **Next recorded step**: move forward through the same recorded session
- **Return to latest**: restore the current live simulation state

Historical inspection is intentionally **read-only**, not destructive
rewinding or trading on a new fork. When inspecting an earlier step:

- Future bars, fills and account state after that checkpoint are not
  displayed; historical analytics accepts an `at` index.
- Active autoplay, new orders and bot activation are disabled.
- AI chat is hidden to prevent viewing later game metrics from the
  perspective of the selected checkpoint.
- The stored live simulation remains unchanged. You can always return
  to the latest committed step.

Snapshots are stored with the game's existing SQLite state. To prevent
unbounded growth, the backend keeps **up to 1500 exact checkpoints** per
game. Existing saves from earlier releases have no full historic state
checkpoints, so exact backward navigation only covers steps recorded
after the upgrade and/or their next modifications. Their older historical
charts and fills remain available in the regular analytics views.

The original local browser Trading Terminal replay also provides
in-memory historical checkpoints and read-only return-to-latest viewing.
That terminal timeline does not persist through browser reload, just as
its prior local replay state did not persist.

## Important distinction

When viewing an earlier step, the simulator **does not re-run trades**,
edit history, erase later executions, or reveal outcomes of pending
orders. Non-destructive backward inspection is different from branching
a new strategy experiment from an old timepoint. Future work can add
explicit branches with a separate session ID and separate state.

## Endpoints

- `GET /api/arcade/{id}/at/{index}`
- `GET /api/portfolio-seasons/{id}/at/{index}`
- `GET /api/arcade/{id}/analytics?at={index}`
- `GET /api/portfolio-seasons/{id}/analytics?at={index}`

The read-only endpoint returns only data visible at the selected saved step
while leaving the active session untouched. The backend includes tests
for current-state preservation and hidden-future access checks.
