# Vercel website with one shared password and private desktop data

Your permanent website is **https://trading-simulator-pp-48b0.vercel.app**.

Visitors need only the **one fixed password you choose**. They do not
need to install Cloudflare, enter a tunnel URL or handle a long API token.

## Architecture and privacy

- **Vercel:** React frontend and a very small `/api/bridge-location`
  discovery function. It stores NO research, strategy source code, models,
  actual fills, portfolio data, access passwords or login sessions.
- **Vercel Global Config:** One non-secret record with the latest temporary
  Cloudflare tunnel URL. This enables automatic lookup when a Quick Tunnel
  changes after restarting the desktop.
- **Your desktop:** FastAPI, Ollama, saved strategies, SQLite databases, the
  trading machine, and the salted password verifier. Login requests and
  subsequent authorized API calls go directly to the desktop through
  Cloudflare HTTPS. Vercel does not proxy the trading data.
- **Browser:** Holds a short-lived private API session in tab memory.
  Password and session token are not persisted in browser storage or cookies.

This can run within Vercel Hobby's included Global Config quota when the
tunnel is not restarted excessively. The desktop and Internet connection
must stay on. Global Config stores only connection metadata, not financial
data.

## Owner: first-time setup

1. Install cloudflared if needed: `winget install -e --id Cloudflare.cloudflared`.
2. On your PC, update the project:
   ```powershell
   cd E:\Trading-Simulator
   git pull
   powershell -ExecutionPolicy Bypass -File .\start-private-bridge.ps1
   ```
3. The script prompts for your **shared web access password** twice.
   Choose a unique, strong password of at least 12 characters. Only a
   salted password verifier is written to the private, Git-ignored
   `.local-state/private-bridge/password-hash.txt`.
4. The script will ask once for your **Vercel access token**. Create a
   token at https://vercel.com/account/tokens with permission to update
   the Trading Simulator team's Global Config. Paste it into the hidden
   local PowerShell prompt. It is stored in Git-ignored
   `.local-state/private-bridge/vercel-token.txt` on your PC, not in
   Vercel's public frontend or GitHub. Treat it as a sensitive credential.
5. The script starts your local API, creates a temporary Cloudflare Quick
   Tunnel, finds the tunnel URL from the process logs and updates the
   connection directory automatically.
6. Share only the **Vercel website URL and your chosen access password**
   with trusted visitors. Do not share your desktop logs, Vercel access
   token, or raw strategy backups.

**Automatic discovery is handled by the desktop launcher, not ChatGPT.**
After a valid PP-team write-authorized Vercel token is saved locally, every
startup registers its new Cloudflare Quick Tunnel URL in Global Config.
If the tunnel process exits, the launcher restarts it and publishes the
replacement URL automatically. Transient publish failures are retried.
The browser also refreshes the directory every 30 seconds while a user is
connected, so it can follow a new tunnel without needing a new address or
re-entering the password while the same backend session remains valid.

**The Vercel token is owner-only infrastructure authorization.** Visitors need
only the permanent website and the single shared web password. The token
is not a visitor credential or an alternate way to sign in. It must be
configured once and renewed if revoked, expired, or unauthorized.

To reset the shared password:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-private-bridge.ps1 -SetPassword
```

Stop the previous bridge first. Changing the password or restarting the
backend revokes existing in-memory sessions. Password sessions expire
after eight hours. The password is never sent to Vercel.

## Visitor: every login

1. Open https://trading-simulator-pp-48b0.vercel.app.
2. Enter the **shared access password**.
3. Select **Open trading workspace**.

The frontend fetches the current tunnel location automatically via
`/api/bridge-location`. It posts the password directly to the desktop
over HTTPS. The desktop checks a salted PBKDF2 password verifier, enforces
a failed-login limit and returns a random temporary session token.
Subsequent direct browser-to-desktop API requests carry that session.

If the PC is off, the tunnel is down, the owner token is not configured,
or Vercel Global Config is unavailable, the login screen clearly reports
that the desktop cannot be reached. No synthetic responses are passed off
as live data.

## Access control and limitations

**All visitors using the shared password access the same private data and
currently have the same application permissions.** That includes the
ability to edit strategies or trade records through the website. Share
this password only with people you fully trust. For view-only access,
we will need a separate permission system before inviting viewers.
This password does not control your Windows desktop; the tunnel serves
only the local FastAPI API, not Remote Desktop or arbitrary PC files.

- The owner may still use `start-local.ps1` to work entirely offline.
- The independent `start-live-machine.ps1` worker remains separate.
- No broker order execution is enabled by this website access.
- The Cloudflare tunnel endpoint is publicly reachable, but
  sensitive API requests require a valid expiring session.
- Server-side login is rate-limited per client and globally, although
  a shared password does not supply per-user audit identity or MFA.
- HTTPS protects connection traffic, which still traverses Cloudflare.
- CORS permits only the explicitly approved Vercel origin.
- Do not commit your `.local-state`, `.env`, private strategies,
  passwords or Vercel access tokens. Existing Git privacy checks apply.
- On Vercel Hobby, connection discovery is small and should typically
  fit included quotas. Your own power, Internet and domain (if used)
  are separate costs.
- This is personal access, not a production-grade multi-user trading
  service. For stronger protection add individual accounts, MFA,
  Cloudflare Access, explicit roles and security logging.

## Older manual token mode

For troubleshooting only, the previous manual URL and long token bridge
can still be started using:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-private-bridge.ps1 -LegacyToken
```

The public website is designed for the new password-only workflow, so
this legacy mode is not the normal website sign-in experience.

## Failure modes

- **Tunnel directory update failed:** First run `git pull` and restart
  `start-private-bridge.ps1`. The launcher now prints the exact safe
  publishing failure reason in its final error message, even if the
  Python subprocess error stream is hidden by PowerShell. No secrets
  or private strategy data are included in the diagnostic. Earlier
  launchers called the removed Vercel `/v1/edge-config` endpoint;
  current releases use `/v1/global-config`. Do not recreate your
  shared web password or reinstall Cloudflare.
- **Manual fallback without a Vercel API token:** If the directory publisher
  cannot authenticate, start the password-protected backend and Cloudflare
  tunnel with `powershell -ExecutionPolicy Bypass -File .\\start-private-bridge.ps1 -ManualDirectory`.
  The launcher will keep the tunnel running and print ONLY its public
  `https://...trycloudflare.com` address. The owner can then publish that
  URL manually through a trusted authenticated Vercel client. No browser
  password, API token or strategy source should be shared. Unlike automatic
  mode, this manual registry update must be repeated each time the Quick
  Tunnel URL changes.
- **HTTP 401:** The locally saved Vercel access token is invalid or expired.
  Create a new token at https://vercel.com/account/tokens and run
  `powershell -ExecutionPolicy Bypass -File .\\start-private-bridge.ps1 -ResetVercelToken`.
  The flag replaces only the locally saved Vercel publishing token. It does
  NOT replace the website's shared password.
- **HTTP 403:** The saved publishing token cannot write Global Config for
  the **PP (`pp-48b0`) team**. Create a new access token at
  https://vercel.com/account/tokens and choose PP, not Personal Account.
  Either restart with `-ResetVercelToken` or, on an interactive launcher,
  accept the new in-place token prompt when HTTP 403 is returned. The script
  retries publishing while the current tunnel stays online. The shared
  password and private trading data are unchanged.
  **Recovery behavior:** On HTTP 401 or 403, the current launcher keeps the
  password-protected desktop API and tunnel running and prints the temporary
  Cloudflare address for the owner. The permanent Vercel website cannot find
  that bridge until the owner manually registers the displayed URL into the
  team's Global Config `bridge` key (value shape `{"url":"https://...trycloudflare.com"}`)
  using an authenticated Vercel client. Only submit the ephemeral URL. Never
  submit a password, authorization token or private trading data. This manual
  registration must be repeated whenever the Quick Tunnel changes.
- **HTTP 404:** Pull the latest code, which uses the current
  `/v1/global-config` endpoint. If it still fails, the token may belong
  to another Vercel team or account.
- **Missing token:** Owner creates a Vercel access token with access to
  the correct team's Global Config and enters it once on the desktop launcher.
- **Vercel locator is offline:** Confirm that `start-private-bridge.ps1`
  remains running, and review
  `.local-state/private-bridge/cloudflared.stderr.log`.
- **Incorrect password:** Retry carefully, or ask owner to rotate it
  with `-SetPassword`. Repeated attempts are temporarily throttled.
- **Network interruption:** Restart the desktop launcher. It publishes
  the new Quick Tunnel address. The frontend URL remains unchanged.
- **No backend while desktop is off:** Vercel serves only the website.
  The trading worker and research databases stay on your computer.

See [LIVE_MACHINE.md](LIVE_MACHINE.md) and
[STRATEGY_PRIVACY.md](STRATEGY_PRIVACY.md) for operational boundaries.
