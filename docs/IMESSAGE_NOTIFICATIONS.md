# iMessage notifications (owner-only beta)

## Current implementation

The Windows **Live Strategy Machine** can deliver outbound notification alerts
through your own **BlueBubbles** server running on a Mac signed into Apple
Messages. This is **optional** and is not part of the Cloudflare website
bridge. Visitors continue to use only the Trading Simulator website password.
No account, relay password, chat destination, or notification details are
published through Vercel or the public GitHub repository.

**What works in code:** opt-in outbound iMessage for pending trading signals,
open alerts and repeated critical alerts through the existing persistent
SQLite delivery receipt and deduplication pipeline. The transport sends
short, generic privacy-preserving notices by default. Tests mock requests,
so no real iMessage is sent by CI.

**Not implemented:** receiving commands or acknowledgments from iMessage,
individual user identities, read/delivery receipt reconciliation, or automatic
broker execution. Sending is disabled until the owner configures the relay.

## Apple device requirement

Apple does not provide a supported native iMessage sending API on Windows.
BlueBubbles is a third-party Mac-hosted bridge and must have an actively
signed-in Messages account on the Mac. An iPhone alone is **not sufficient for
this specific transport**. You may use a separate Mac from the Windows
trading machine. Keep its Messages account and BlueBubbles service running.

Official setup: https://docs.bluebubbles.app/ . Review security and platform
requirements before installing. Choose an HTTPS connection to the owner-controlled
BlueBubbles server. Do not expose an unauthenticated local server to the Internet.

## Local Windows configuration

1. Install and configure BlueBubbles on an Apple Mac under your control.
2. In BlueBubbles, find the HTTPS server URL, the server password and the GUID
   of an **existing iMessage chat**. Prefer a chat with an Apple ID/number
   different from the sending Apple ID, so the alert arrives as a message.
3. Open your local `E:\\Trading-Simulator\\.env` and add:

   ```dotenv
   TRADING_SIM_IMESSAGE_SERVER_URL=https://your-own-mac-relay.example
   TRADING_SIM_IMESSAGE_PASSWORD=your-private-server-password
   TRADING_SIM_IMESSAGE_CHAT_GUID=iMessage;-;recipient@example.com
   TRADING_SIM_IMESSAGE_INCLUDE_DETAILS=0
   ```

4. Restart the private monitoring worker (not just the Vercel website):

   ```powershell
   cd E:\\Trading-Simulator
   powershell -ExecutionPolicy Bypass -File .\\start-live-machine.ps1 -Stop
   powershell -ExecutionPolicy Bypass -File .\\start-live-machine.ps1
   ```

5. To send **one owner-approved, generic test iMessage**, run this in the
   Windows project folder and confirm the interactive prompt:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\\start-live-machine.ps1 -TestIMessage
   ```

   This test uses no saved strategy or portfolio data. If the Mac relay
   accepts the message, confirm receipt on the Apple device. Normal worker
   notifications still trigger only for pending signals and open alerts.
   The private website's notification delivery history will show successful
   sends and failed attempts; the API process and worker may have different
   environment settings, so the browser's channel listing alone is not proof
   that the background worker has the iMessage settings loaded.

**Generic notice default:** With `TRADING_SIM_IMESSAGE_INCLUDE_DETAILS=0`,
messages say only that a trading review or critical system alert needs your
attention. No confidential strategy rules, selected parameters, fills,
position sizes, symbols or account balances are sent to Apple Messages.
Setting `TRADING_SIM_IMESSAGE_INCLUDE_DETAILS=1` sends the existing
notification title and message text externally. Do this only after reviewing
that text and accepting the privacy implications.

The BlueBubbles REST API currently authenticates using a password in the URL
query string. Your Mac server and any HTTPS reverse proxy may log it. Use a
unique relay password, restrict access to trusted clients, and keep its
configuration and logs private. Never share the `.env` or run a bridge
without HTTPS. The Mac and Windows PC may each need to remain online.

The send endpoint is `POST /api/v1/message/text` using an explicit
`iMessage;-;` or `iMessage;+;` chat GUID, with an authenticated request.
Explicit iMessage GUIDs avoid automatic fallback to SMS. The URL is
validated as HTTPS; redirects are refused. Raw provider errors and secrets
are never saved in the trading delivery journal.

## Delivery semantics and safety

The worker uses the existing per-channel SQLite delivery rows. A normal
notification is not sent twice once successfully recorded. Open critical
alerts are resent after a 15-minute cooldown until acknowledged. A network
failure is recorded as a generic exception category and may be retried.
This is **best effort**, not exactly-once messaging: a response lost after
BlueBubbles sends a message can result in a duplicate on retry. No trade or
broker action is ever initiated from an iMessage notification.

### Data locations

- Live worker deployment state, signal queue, alerts, and delivery receipts:
  `data/live_machine.sqlite3` (private, Git-ignored)
- Local recipient and BlueBubbles password: `.env` (private, Git-ignored)
- Live worker logs: `.local-state/live-machine/` (private, Git-ignored)
- Vercel Global Config: **only the Cloudflare private-engine URL**, never
  message recipients, passwords, strategy data, or message bodies

## Future work

Incoming iMessage commands and acknowledgments require a separate verified
sender allowlist, signed webhook authentication and human approval rules.
They are not enabled by this initial outbound-only adapter.
