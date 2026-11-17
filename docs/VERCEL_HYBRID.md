# Vercel frontend + private local trading engine

**Architecture:** The public Vercel deployment serves only the compiled React
application. It does not host a Python API, a database, historical market
archives, research outputs, your proprietary trading strategies, Ollama,
actual trading records or secrets.

The frontend starts with a clearly labeled synthetic chart and an
**explicit private-engine connection screen**. It does not attempt to fetch
any personal data until you connect a local/private backend.

## 1. Public website

The project is configured for Vercel with `vercel.json`:

- Framework: Vite
- Install: `npm install`
- Build: `npm run build`
- Output directory: `dist`
- Production / Preview / Development build environment:
  `VITE_CLOUD_FRONTEND=1`

GitHub integration should deploy main to the project's permanent
`*.vercel.app` production URL. This static deployment has no database
or Python runtime costs, subject to the account's Vercel usage and plan rules.

**Do not add any `VITE_*` secrets.** Vite embeds those variables in
public JavaScript. The flag above is non-sensitive; it selects a safe
connection gate instead of silently loading private API requests.

## 2. Start the private engine on your own Windows PC

The first time, install cloudflared. If already installed by winget, the
launcher also searches common Windows installation locations automatically.

From your local `Trading-Simulator` checkout, run:

```powershell
git pull
powershell -ExecutionPolicy Bypass -File .\start-private-bridge.ps1 -AllowedOrigin "https://YOUR-VERCEL-URL.vercel.app"
```

Replace that example with the **exact origin shown in your browser**,
without a path. The connection page also displays a command with the
current origin to copy. If installed cloudflared cannot be found, pass
`-CloudflaredPath "C:\path\to\cloudflared.exe"`.

This launcher checks dependencies, starts the private FastAPI process on
`127.0.0.1:8002`, and opens a temporary Cloudflare tunnel to it.
Unlike `start-public.ps1`, this process uses your EXISTING private
`data/` databases and should not be given to untrusted users.

A private bridge requires:
- `TRADING_SIM_PRIVATE_BRIDGE=1`
- `TRADING_SIM_PRIVATE_API_TOKEN` containing at least 48 random characters
- `TRADING_SIM_ALLOWED_ORIGINS` listing exact HTTPS UI origins.

The launcher handles these automatically. The access token is randomly
generated and stored in gitignored `.local-state/private-bridge/api-token.txt`
on your PC. The local file is not encrypted, so keep your computer/account
secure. You can rotate it on restart by adding `-RotateToken`.

## 3. Connect in the website

1. Keep the local PowerShell private-bridge terminal running.
2. Find the `https://...trycloudflare.com` URL printed by cloudflared.
3. Enter that URL in the Vercel site's **Engine URL** field.
4. Copy the access token printed in your private-bridge terminal into
   **Private access token**. Never share it with public visitors.
5. Select **Open trading workspace**.

The browser first checks `/api/health`, requires valid authentication,
and verifies that it is connecting to a backend in `private-bridge`
mode. Only then does it load your trading workspace. Every subsequent
API request is sent directly from your browser to your own backend using
a bearer token in an authorization header.

**The browser does not send the token to Vercel, and it is kept in
memory only**, not localStorage/sessionStorage/cookies. Refreshing the
page requires reconnecting. The browser receives requested private
strategy and portfolio data for display; Vercel does not persist those
API responses, but they transit Cloudflare. Use browser security
hygiene and never expose access tokens in shared screenshots.

### Availability and costs

- Vercel can host the static UI continuously.
- Your private API works only when your PC and cloudflared are running.
- A Quick Tunnel URL changes on restart, even though the Vercel URL stays
  stable. Reconnect with the new tunnel URL.
- No managed database, hosted Python/AI worker, or paid model API is required.
- Historical market-data provider limits and network bandwidth still apply.
- The optional private bridge is a **personal access tool**, not an
  authenticated multi-user production service.

The default local setup `start-local.ps1` remains unchanged. It serves
the website and API together on local ports 5173/8000 for ordinary use.
The separate public demonstration launcher `start-public.ps1` still uses
its isolated 4173/8001 sandbox, with no access to real strategy records.

## Security boundaries

- Vercel: static public frontend only. No private database, secret,
  strategy, prediction output or trading record is included in the bundle.
- FastAPI private bridge: defaults off, fails to start without a strong
  token and exact HTTPS origin allowlist.
- Cross-origin preflights: only allowlisted frontend origins.
- Every private `/api/*` call requires the bearer token, including
  health checks; unauthenticated calls return HTTP 401.
- Unknown browser origins are rejected. Data responses add
  `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.
- The API listens on localhost, not `0.0.0.0`.
- Never connect a private engine to the anonymous public demo tunnel.
- Do not put the private API token in a Vercel environment variable,
  repository, GitHub Actions log, bug report or issue.
- If the token is leaked, stop the tunnel and restart with
  `-RotateToken`. Rotate other affected credentials as necessary.

**Important:** CORS does not replace authentication. The access token
protects requests, and a cloudflared Quick Tunnel is still a publicly
reachable endpoint. For long-term confidential production access, add
Cloudflare Access, user authentication, hardened rate limiting,
device access control, backups, monitoring and a persistent named tunnel
before considering real financial use.

## Future 24/7 live strategy machine

A statically hosted website is NOT a 24/7 strategy engine. Keeping the
browser open or scheduling requests from it is not reliable enough for
actual trading decisions. The next system component should be a
persistent, local engine service with a durable event/signal queue,
health monitoring, notifications and independent scheduler.
Do not advertise live auto-trading as implemented by this deployment.
