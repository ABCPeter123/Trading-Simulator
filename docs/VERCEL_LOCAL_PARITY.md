# Live Vercel baseline versus local npm development

**Production deployment stays frozen until an explicitly approved major milestone.**

The verified most recent READY, production-targeted deployment is pinned in
[config/production-baseline.json](../config/production-baseline.json).

- Production source commit: `f079adf8d8133892106985b57d068981ba9987c2`
- Published 2026-11-17 19:21:15 UTC
- Snapshot: https://trading-simulator-8zujax723-pp-48b0.vercel.app
- Development: GitHub `main`, already ahead of production.

**Do not reset the development main branch to that old commit.** Main already
contains next-milestone portfolio research, queue and local worker improvements.
Instead the script creates a **separate local snapshot** at exactly the live
source commit. The newer local UI remains the working version.

## One-command comparison

For the simplest setup, update your checkout and run:

```powershell
cd E:\Trading-Simulator
git pull
.\start-local.ps1 -CompareVercel
```

Or use `npm run dev:compare` in PowerShell. The launcher starts both
frontends along with the normal local Python API and research worker.
Opening the baseline for the first time installs its own npm packages.

- **http://127.0.0.1:5173**: the evolving development application
- **http://127.0.0.1:5174**: the exact source of the currently published site

The live website is untouched. You can also run the two frontends
manually using the steps below.

## Start the two UIs side-by-side on your Windows laptop

In PowerShell terminal 1:

```powershell
cd E:\Trading-Simulator
git pull
.\start-local.ps1
```

Open **http://127.0.0.1:5173**, your evolving development UI, with local
FastAPI and background research worker.

In terminal 2:

```powershell
cd E:\Trading-Simulator
.\scripts\start-vercel-baseline.ps1
```

Open **http://127.0.0.1:5174**, the preserved Vercel source baseline.

The script fetches the production Git commit if necessary, then creates a
**detached** Git worktree in the sibling folder
`E:\Trading-Simulator-Vercel-Baseline`. It installs npm dependencies separately,
serves on loopback only, and never changes or resets your main worktree.
It does not deploy to Vercel.

**Authentication split:** In local Vite development (`npm run dev`,
`start-local.ps1`, or `start-local.ps1 -CompareVercel`), the Trading
Simulator application opens directly. There is **no local password
prompt**. The local Python backend is bound to 127.0.0.1 and explicitly
disables private-bridge mode. Even a stale `VITE_CLOUD_FRONTEND=1`
variable cannot show the Vercel gateway in development mode.

The Vercel production build is different: it retains its
password-protected Cloudflare private engine connection, token validation
and server-side authorization. No hosted authentication was removed.
The local Vite LAN option is not password protected; only use it on a
trusted private network.

Both local frontends use the existing private Python API on 127.0.0.1:8000
for data. These **local application screens are source-parity previews**, not
byte-for-byte copies of Vercel's minified bundle. Live Vercel requires the
remote password/Cloudflare gateway, while local dev intentionally uses
the localhost API without the remote-login screen. The same post-login
component source, features and navigation can be compared.

The local API is from the *newer* development checkout, and may expose
additional private endpoints; this does not rewrite old production code.

Use Ctrl+C in the second terminal to stop the snapshot UI. Do not edit,
commit or push from the detached baseline worktree.

## Inspect changes since production

```powershell
npm run baseline:status
npm run typecheck
npm run verify:local
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

The first command lists frontend files changed since the live Vercel
deployment and checks that `vercel.json` still disables automatic
Git deployments. This operation is read-only and does not use Vercel.

Current development is intended to be a **superset** of the live source.
Compare both local UIs before milestone release to avoid accidental
loss of functionality or inconsistent layout.

## Planned sync back to Vercel

1. Continue local development and tests without deploying.
2. Validate desktop/mobile layouts, English/Chinese, research queue,
   historical simulations, private data isolation and all prior features.
3. Get the owner's **explicit approval** for one major release.
4. Publish the exact tested revision only then, while maintaining
   the agreed release freeze for everyday commits.
5. Verify the new production commit is READY, update
   `config/production-baseline.json`, and use it as the next local comparison.

The existing production website remains unchanged until that approval.

See [local-first release policy](LOCAL_FIRST_RELEASE_POLICY.md).
