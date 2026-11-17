# Share the live Trading Simulator on the internet

The project includes a Windows launcher for a **temporary public HTTPS website**
through a Cloudflare Quick Tunnel. Anyone with the generated URL can use the
live app from their own phone or computer, without being on your Wi-Fi.
No router port forwarding, public IP address, Cloudflare account, or domain
is required for a Quick Tunnel.

This is a shared demonstration environment, separate from the owner's private
local simulator. It is not a hosted, always-on production deployment.

## Start sharing

On the **Windows PC that runs the simulator**, open PowerShell in the
Trading-Simulator repository and install the Cloudflare tunnel agent once:

```powershell
winget install -e --id Cloudflare.cloudflared
```

The launcher automatically checks PATH, standard Windows MSI installation
directories (including `C:\Program Files (x86)\cloudflared`), user and
machine PATH, and common WinGet portable locations. **A successful winget
install does not always make the command available in PowerShell.**
You do not need to reinstall if the binary already exists.

Update the project and launch the public site:

```powershell
git pull
powershell -ExecutionPolicy Bypass -File .\start-public.ps1
```

The launcher:

1. Checks project dependencies.
2. Builds the React app for production with a **Public Demo** banner.
3. Starts an isolated Python API on `127.0.0.1:8001`, with data stored
   exclusively under `.local-state/public-demo/`.
4. Serves the production frontend on `127.0.0.1:4173`. Its `/api`
   proxy targets **8001**, never private **8000**.
5. Verifies that the frontend proxy reaches the API in `public-demo`
   mode, then launches the Cloudflare Quick Tunnel.

Cloudflare prints a URL similar to:

```text
https://some-random-name.trycloudflare.com
```

**Copy the actual URL printed on your PC**, then share it. The URL is
different each time you restart the tunnel.

Leave the PowerShell window open and your computer awake. Press **Ctrl+C**
to close the tunnel and shut down its demo servers. Your normal
`start-local.ps1` instance can remain running independently.

## What visitors can do

The public site has the same layout and research interfaces as the local
frontend. Public visitors share a **sandbox** in which they can start
simulations, advance historical replay, experiment with paper positions,
inspect charts, and save demonstration strategies. Visitors can see and
change each other's sandbox sessions, balances and strategies. This is
intentional for short-lived demonstrations and is not suitable for private
individual user accounts. **NEVER upload, paste, import or activate your real
private strategy or proprietary parameter sets on the public demo.** Other
visitors can read them. Do not enter credentials or personal financial records.
See [the mandatory strategy privacy policy](STRATEGY_PRIVACY.md).

The sandbox uses its own databases, custom-instrument imports and market
archives. The owner's private `data/` directory, locally saved accounts,
previous simulation sessions and strategy library are never connected to
the public API. The public backend runs with `TRADING_SIM_AI_PROVIDER=off`:
**no local Ollama access and no paid OpenAI API calls**. On startup the API
checks this isolation and refuses to start if it is misconfigured.

Public historical market queries may still use public Yahoo Finance or
Coinbase data, subject to their rate limits. A public visitor can request
market data and use local CPU, RAM, disk and network bandwidth; don't share
the link with untrusted large audiences or treat it as a production website.

## Troubleshooting

- **Installed through winget, but cloudflared is still not found:**
  the MSI can install the executable without adding its directory to PATH.
  The latest launcher searches standard locations automatically.
  First run `git pull` and try the launcher again. Verify installation:

  ```powershell
  winget list -e --id Cloudflare.cloudflared
  Get-ChildItem "${env:ProgramFiles(x86)}\cloudflared" -Filter cloudflared.exe -ErrorAction SilentlyContinue
  ```

  If the file exists in another location, pass that exact location:

  ```powershell
  powershell -ExecutionPolicy Bypass -File .\start-public.ps1 -CloudflaredPath "C:\path\to\cloudflared.exe"
  ```

  Alternatively set `TRADING_SIM_CLOUDFLARED` in your PowerShell process
  to the executable path. The launcher accepts portable files named
  `cloudflared-windows-amd64.exe` as well.
- **Port 8001 or 4173 already in use**: stop the earlier public demo.
  They intentionally do not reuse private ports 8000 and 5173.
- **Startup or 502 errors**: inspect the four `*.log` files in
  `.local-state/public-demo/` and confirm the Python API starts.
- **Tunnel cannot start with an existing Cloudflare configuration**:
  Quick Tunnels may be blocked by a `config.yml` in your user
  `.cloudflared` directory. Use a clean Quick Tunnel environment or
  configure a named tunnel.
- **Broken public URL**: the PC must stay online, and cloudflared,
  the demo backend, and the preview server must all still be running.
- **Different URL after restarting**: this is normal for Quick Tunnels.

Quick Tunnels are designed for temporary sharing. For a stable custom
domain and higher reliability, configure a named Cloudflare Tunnel or
deploy the frontend/backend to managed hosting. This launcher does not
silently publish an always-on website or create a Cloudflare account.

## Technical design

```text
Private owner only:       http://127.0.0.1:5173
                           | -> private API :8000 -> data/

Public HTTPS URL:         https://<random>.trycloudflare.com
                           | Cloudflare tunnel (outgoing connection)
                           v
                         http://127.0.0.1:4173
                           | production Vite preview
                           | /api -> isolated API :8001
                           v
                         .local-state/public-demo/
```

Both frontend and backend remain bound to loopback. The tunnel exposes
**only** the compiled production preview, not Vite's development source
server or Python API port directly.

References: [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/),
[Vite preview options](https://vite.dev/config/preview-options).
