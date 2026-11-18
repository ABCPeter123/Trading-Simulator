# Live strategy machine and trade monitoring

Trading Simulator now includes a private, low-frequency **strategy signal
worker**, separated from the browser and web API. This is a semi-automated
research-to-execution system, not an automatic brokerage trading bot.

The source code is public. Your saved strategy rules, selected optimizer
parameters, live signals, notifications and actual trade journal are stored
in Git-ignored local files only. Never include proprietary data in
commits, issue reports, screenshots, CI logs or a shared public demo.

## Run the strategy machine

Use PowerShell in your private Windows project checkout:

```powershell
git pull
powershell -ExecutionPolicy Bypass -File .\start-local.ps1 -SetupOnly
powershell -ExecutionPolicy Bypass -File .\start-live-machine.ps1
```

The final command launches a **separate background Python worker**,
which continues evaluating conditions and sending alerts after the browser
or FastAPI website is closed. Keep your PC powered on and connected to
the internet. The worker will not run if the computer sleeps or turns off.

Other commands:

```powershell
# Run one evaluation/notification cycle interactively (safe diagnostic)
.\start-live-machine.ps1 -Once

# See latest logs without sharing strategy contents
Get-Content .\.local-state\live-machine\worker.stderr.log -Tail 30

# Install an optional Windows logon task to keep the worker running
.\start-live-machine.ps1 -InstallAtLogon

# Stop the local worker (and an active scheduled-task process if present)
.\start-live-machine.ps1 -Stop
```

The scheduled task uses a foreground worker under Task Scheduler with
restart-on-failure settings and can start after the selected user logs in.
It is not a cloud service and does not operate while Windows is off.

The web UI can be reached through:
- Local `http://127.0.0.1:5173` with `start-local.ps1`
- Your stable Vercel frontend at
  [trading-simulator-pp-48b0.vercel.app](https://trading-simulator-pp-48b0.vercel.app)
  after connecting the private authenticated API tunnel with
  `start-private-bridge.ps1`.

To use the private Vercel interface, open the private-bridge PowerShell
terminal. Its line **"Paste this access token into the Vercel site"**
is followed immediately by the token. The Cloudflare tunnel HTTPS
address is printed later. Do not paste your access token in GitHub or
messages to others.

## Daily workflow

1. **Strategy Lab & Backtesting:** create or refine single-asset or
   cross-asset strategy rules and save a named private version.
2. **Strategy Discovery:** select a stock/ETF, drawdown limit and
   position allocation. Compare a controlled grid of simple SMA
   crossovers on chronological train (60%) and validation (20%)
   periods. View the selected candidate on an untouched held-out
   test period (20%). Strategies and experiment history remain local.
3. **Live Strategy Machine:** deploy a saved version in paper mode.
   Only the named saved strategy ID is used. The worker freezes its
   code snapshot in private SQLite and never mutates the version
   in response to optimization.
4. **Live monitoring:** after 9:15 AM New York time on trading weekdays,
   evaluate the latest **completed previous trading-day candle**.
   Evaluate each source once daily and store the rationale, price
   reference, source date and validity window. Signals remain
   human review items, never broker fills.
5. **Notifications:** send alerts via locally configured Discord or
   email. Ordinary messages are deduplicated. Critical incidents
   can repeat every 15 minutes until acknowledged. Approaching
   expiry of an unacknowledged recommendation can escalate.
6. **Trade Journal:** after manually trading in your actual broker,
   open **Record fill** from a suggestion. Confirm and edit actual
   quantity, price, fee, timestamp, currency, broker reference,
   notes and asset. You can also record an unsolicited/manual trade.
   All corrections preserve a revision history.
7. **Execution attribution:** compare the actual broker fill with the
   original signal reference price, elapsed hours, expiry window and
   changes to symbol/side. Material deviations create review alerts,
   never automatic broker corrections.
8. **Dashboard and Alerts:** inspect worker heartbeat, risk state,
   completed evaluations, pending action cards, actual confirmed
   holdings, realized results by currency, delivery attempts
   and critical incidents.

The browser may close while monitoring continues. A Windows or
Internet outage stops evaluation. Your scheduled job must run for the
engine to work; Vercel itself only hosts the website.

## Twelve-hour intraday execution evidence

The **Live Strategy Machine** and **Portfolio & Trade Journal** now provide
a read-only execution-window observation panel for recently generated USD
stock/ETF signals. The independent local worker samples the same provider's
five-minute OHLCV feed as the chart service. A private SQLite database
`data/execution_windows.sqlite3` records bounded, restart-safe snapshots.

- Three diagnostic scenarios wait at least **5, 30 or 60 minutes after the
  signal creation timestamp**. A candle qualifies only when its full
  five-minute interval has completed and it falls inside both the
  recommendation expiry and a strict **12-hour** time horizon.
- Only regular U.S. market candles between **9:30 AM and 4 PM New York
  time** are included. Overnight, pre-market and after-hours trading are
  excluded. Exchange holidays, halts and broker product restrictions are
  not validated by these five-minute candles.
- The model uses the **first eligible completed candle** after each
  latency threshold. It estimates a buy/sell price from that candle's
  **opening price**, an indicative half-spread and 8 basis points of
  assumed slippage. These are not broker quotes or execution reports.
- Illustrative liquidity is capped at **1% of that single candle's
  recorded volume**. A partially sufficient candle is reported as
  partial capacity; it is never turned into a confirmed trade. A missing
  or zero-volume candle cannot establish executable capacity.
- A worker that reads a candle more than ten minutes after its completion
  labels it **retrospective**, to distinguish later historical inspection
  from near-real-time observation.
- If no completed eligible candle was seen within the window, the result
  reports exactly that. It does **not** claim the broker was unable to fill.
  Stale/demo/offline feeds, invalid timestamps or malformed OHLCV do not
  overwrite earlier valid observations.
- The original strategy code, actual broker journal and confirmed fills
  stay separate. The monitoring UI may display manual trade execution
  alongside the calculated scenarios, but no calculation edits those fills.
- The public demo cannot call the observation endpoints. Automatic
  observation is restricted to at most 20 recent signals per worker pass,
  within 96 hours of their creation.

An end-of-day U.S. signal at 4 PM cannot meet the following day's 9:30 AM
regular open in 12 hours, since the normal opening is 17.5 hours later.
The observer will not invent an overnight market fill. Its results are
research diagnostics, not broker short-locate checks, verified trade
capacity, or guarantees that a manual trade could execute.

## Notification setup

The worker loads **only allowlisted keys** from your private, Git-ignored
`.env` file on launch. Example values below are placeholders.

Discord: create your own Discord webhook and add this line
to `.env` on your PC:

```dotenv
TRADING_SIM_DISCORD_WEBHOOK=https://discord.com/api/webhooks/your-own-webhook
```

Email (example for an SMTP server supporting TLS):

```dotenv
TRADING_SIM_SMTP_HOST=smtp.example.com
TRADING_SIM_SMTP_PORT=465
TRADING_SIM_SMTP_USER=private-user@example.com
TRADING_SIM_SMTP_PASSWORD=your-app-password
TRADING_SIM_EMAIL_FROM=private-user@example.com
TRADING_SIM_EMAIL_TO=recipient@example.com
```

For SMTP port 587, the worker uses STARTTLS instead of SMTPS on port 465.
For Gmail, use `smtp.gmail.com` and a Google **app password** from an
account with 2-Step Verification enabled. Do not use your normal Gmail
password, share an app password in chat, or check it into Git. Your sender
account must allow authenticated SMTP.

To email comprehensive private trading briefings to multiple recipients,
add these extra keys to the private `.env` on the Windows computer:

```dotenv
TRADING_SIM_NOTIFICATION_CHANNELS=email
TRADING_SIM_EMAIL_TO=recipient-one@example.com,recipient-two@example.com
TRADING_SIM_EMAIL_DIGEST_ENABLED=1
TRADING_SIM_EMAIL_DIGEST_TIME=17:15
```

The live worker sends an **end-of-day briefing on weekdays at 5:15 PM Toronto
time** (or the next worker cycle after that time). Critical alerts and new
trading signals trigger separate prompt emails. Ordinary alerts are
once-per-alert; unresolved critical incidents can repeat every 15 minutes.

The briefing includes action items, signal side/allocation/reference price,
expiry and rationale, active strategies/risk limits, health and market-data
issues, open alerts, confirmed positions, realized P/L by currency, manually
recorded fills, execution deviations, latest evaluations, saved strategy
names and recent optimization progress. It sends both styled HTML and plain
text in the same email. Broker cash, unrealized returns and live valuations
are explicitly marked unavailable instead of invented. Strategy source code
and credentials are not included, although decisions and financial records
inside a report remain sensitive when email is forwarded.

To send a full report **right now** without waiting for 5:15 PM:

```powershell
cd E:\\Trading-Simulator
powershell -ExecutionPolicy Bypass -File .\\start-live-machine.ps1 -SendEmailReport
```

The manual command asks permission before sending a real email, and does not
change the regular weekday schedule. It uses all addresses in
`TRADING_SIM_EMAIL_TO`. A separate email service account may be used as
sender.

**If an email fails or reports `SMTPServerDisconnected`:** update your
Windows checkout with `git pull` and run the safe diagnostic below:

```powershell
cd E:\\Trading-Simulator
powershell -ExecutionPolicy Bypass -File .\\start-live-machine.ps1 -DiagnoseEmail
```

The diagnostic tests both encrypted Gmail SMTP options, **465/SSL** and
**587/STARTTLS**, and authenticates without sending any email. It distinguishes
**connect**, **starttls**, **ehlo**, and **authenticate** failures. The raw
SMTP greeting and server messages are never printed. It only prints
the port, safe failure stage, and exception type. It never prints your
username, app password, recipient addresses or report content.

**If both ports disconnect at authenticate:** Google may have rejected the
app password, or a network/security filter may be interrupting SMTP login.
Verify that `TRADING_SIM_SMTP_USER` is the Gmail account that generated
the app password. The password must be a **16-character app password**
created at https://myaccount.google.com/apppasswords while that account has
2-Step Verification enabled, not the regular Google login password. If
the diagnostic reports the wrong password length, no SMTP login is attempted.
Update only the private `.env` file. Do not paste any credentials in chat.

**If both ports disconnect at ehlo:** the connection drops before password
verification; check VPN, antivirus SMTP scanning, firewall filtering and
the network connection. Try from a different trusted network after fixing
any configuration issues. The program accepts a password displayed with
spaces in groups of four and normalizes it locally. The sender automatically falls back from Gmail SSL
465 to STARTTLS 587 if the connection fails **before login**. Failures
during message submission are not retried on another port because an SMTP
server could have accepted the message before dropping the reply. In that
case, check both recipients before manually resending.

You can additionally check outbound TCP reachability from PowerShell:

```powershell
Test-NetConnection smtp.gmail.com -Port 465
Test-NetConnection smtp.gmail.com -Port 587
```

A successful TCP check does not prove SMTP TLS or login works. If both
ports cannot connect, review your VPN, firewall, router, and ISP egress
rules. The safe diagnostic gives the more useful authenticated result. There is an optional iMessage adapter described in
[IMESSAGE_NOTIFICATIONS.md](IMESSAGE_NOTIFICATIONS.md), but it stays inactive
when `TRADING_SIM_NOTIFICATION_CHANNELS=email`.

Restart the worker after changing its environment variables.
Discord/email traffic leaves your PC by design. Never put tokens,
full strategy code or account details into notifications.

## Protection and fidelity

- A public shared demo cannot read, write or run the private live
  machine. The public URLs do not connect to your trade journal.
- Each deployment is a frozen reference to a saved rule version.
  Paper vs live-monitor requires deliberate user action; neither
  state can automatically send actual brokerage orders.
- Daily signals are edge-triggered based on **completed** candles,
  not a partially formed session. They expire at the next calculated
  weekday 16:00 New York market close. **Exchange holidays and early
  closes are not yet modeled**, so confirm actual market sessions.
- All market input comes from public providers and can be delayed.
  Stale, missing, demo or offline cached data blocks new live
  recommendations and creates a critical incident. Failed sources
  back off to avoid excessive provider polling.
- A deployment's maximum single-recommendation allocation is 25%
  of reference capital, with an adjustable daily signal cap.
  A configurable **realized-loss fuse (default 5% of reference capital)**
  pauses further recommendations and creates a critical alert when your
  confirmed USD realized losses exceed that threshold. Existing real broker
  positions are NOT closed. The fuse uses manually entered confirmed records
  and does not see unrecorded transactions or unrealized losses.
  These are **recommendation constraints**, not enforced brokerage
  limits. You must review liquidity, account cash, portfolio
  risk, borrow availability and execution costs before real trades.
- Confirmation records distinguish a suggested order from what
  actually executed. No backend fill is created until you confirm.
- Manual trade journal uses weighted average long-only cost basis;
  currencies stay separate. It does not reconcile broker statements,
  taxes, cash flows, FX conversion or unrealized P&L yet.
- Model forecasts and optimized candidates are probabilistic and
  hypothetical. Test-set results alone cannot guarantee a working
  or profitable trading strategy.

## Remaining production work

This release is an end-to-end *beta vertical slice*, not a fully
production-ready investment management platform. Features that still
require more engineering and validation include:

- Broker statement ingestion and account reconciliation.
- Robust exposure factor modeling across correlated assets, stress
  regimes, maximum total drawdown checks and model drift monitoring.
- Short positions, financing, margin maintenance, leverage,
  hedge accounting and an end-to-end long/short portfolio solver.
- Multiple time zones, full exchange holiday/early-close calendar,
  data-provider redundancy and reference-data/corporate-action checks.
- Reliable always-on execution on a low-power server or dedicated
  machine with monitoring if the host is offline.
- Broker order integration, which remains **disabled by design**
  until explicitly authorized and hardened.
- Strategy selection across many asset types and model classes,
  rolling walk-forward and regime-aware out-of-sample testing,
  cost sensitivity and risk-budget optimization.
- Multi-account/multi-currency complete cash ledger and tax lots.

See [PRODUCT_VISION.md](PRODUCT_VISION.md) and
[STRATEGY_PRIVACY.md](STRATEGY_PRIVACY.md).
