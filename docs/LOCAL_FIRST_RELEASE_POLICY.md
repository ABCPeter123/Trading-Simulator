# Local-first development and milestone-only Vercel releases

**Effective November 17, 2026. Permanent until the owner explicitly approves
a major production release.**

The owner chose to **stop automatically publishing incremental website
changes** and conduct UI, backend, data and strategy research testing on the
local Windows machine using npm/Vite and Python. GitHub remains source
control, not a release trigger. Existing live Vercel sites are **not
paused or deleted**.

## All Vercel projects audited

Team: `PP` (`pp-48b0`) on Vercel Hobby. Nine existing projects:

| Vercel project | Deployment model | Update policy |
| --- | --- | --- |
| trading-simulator | Vite frontend, Python research locally | Git auto-deploy disabled in repository `vercel.json` |
| peter-pu-quant-arcade | Personal website and interactive projects | No tracked Git-linked project in the team connection report; do not request deployments until a milestone |
| peter-pu-billiards-engine | Billiards application | No tracked owner Git-linked project in the team connection report; do not deploy until a milestone |
| peter-pu-billiards-ui-src | Billiards frontend | No tracked owner Git-linked project in the team connection report; do not deploy until a milestone |
| background-remover | Browser-side image AI / Vite | Git auto-deploy disabled in repository `vercel.json` |
| cookiequant-dashboard | Static dashboard plus telemetry function | Git auto-deploy disabled in `dashboard/vercel.json` |
| smart-irrigation-platform | Expo web UI | Git auto-deploy disabled in root `vercel.json` |
| smart-irrigation-api | Vercel functions | Git auto-deploy disabled in `backend/vercel.json` |
| peter-pu-minesweeper | Browser game | Git auto-deploy disabled in repository `vercel.json` |

**Do not run** `vercel deploy`, `vercel --prod`, dashboard Create
Deployment, a deployment hook, REST deployment creation, production
promotion, GitHub Action deployment, or any equivalent release for normal
feature iterations. This applies across **all nine projects**. The
`git.deploymentEnabled=false` control blocks automatic Git deployments
for the linked repositories we can modify. The remaining three projects
must remain on existing production versions through a no-deploy policy;
their external/manual deployment sources were not modified.

Source-control commits, PRs, unit tests, linting, UI changes and
mock/synthetic research can proceed without a production release.

## Recommended development workflow: Trading Simulator

Windows PC:

```powershell
cd E:\Trading-Simulator
git pull
.\start-local.ps1
```

This runs the Python FastAPI backend on `127.0.0.1:8000`, the Vite dev
frontend on `127.0.0.1:5173`, and a local portfolio research-queue
worker in its own terminal. Opening `http://127.0.0.1:5173` provides
the full research UI with live local API calls. Vite's development proxy
forwards `/api` to the loopback-only Python backend. **No Vercel
deployment or Vercel usage is required for local testing.**

For UI-only work when the backend and research worker are already up:

```powershell
npm run dev
```

For testing on a phone or another computer on the **same trusted Wi-Fi**:

```powershell
.\start-local.ps1 -Mobile
```

The launcher prints the appropriate `http://<PC-LAN-IP>:5173` address.
If port 5173 already has a loopback-only Vite server, stop that server
first and rerun with `-Mobile`. The equivalent direct frontend command
is `npm run dev:lan`, which requires a separate local Python backend
to be running. Use `npm run dev` for loopback-only access.

**LAN security:** the dev server is deliberately unauthenticated
and proxies a private API. Do not expose port 5173 to the public internet,
forward it through the router, publish it through Cloudflare Quick Tunnel,
or use it on untrusted Wi-Fi. Do not use the development server for public
testing or production website visitors. Restrict Windows Firewall access
to trusted Private networks. Browsers on the local network may access
private trading data while the dev server is running. Use the existing
password-protected private bridge for authorized remote access, not Vite.

### Local validation before committing

```powershell
cd E:\Trading-Simulator
npm run typecheck
npm run verify:local
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

The last command runs synthetic offline backend tests. Source code,
generic tests and docs may go to GitHub; the actual strategies, research,
credentials and financial records never may.

For other projects, prefer their existing package scripts:
- Background Remover: `npm run dev`, `npm test`, `npm run build`
- CookieQuant Dashboard: `npm run build` inside `dashboard`, plus
  root `npm run check` for its toolkit
- Smart Irrigation: `npm run web`, `npm run typecheck`,
  `npm run build:web`; backend verification should run separately
- Minesweeper: Python desktop testing and the browser UI's existing
  source-specific workflow; no Vercel deployment is necessary

## Major milestone release checklist

A production release requires all of these conditions, with the owner
explicitly authorizing it:

1. A demonstrable product milestone, not an isolated bug fix or visual
   adjustment. Consolidate many local/GitHub changes into a single release.
2. The local application is usable on desktop and mobile, with verified
   English/Chinese coverage and no regression to existing features.
3. Synthetic unit/functional tests and local production builds pass.
   Check real research workflow in the **owner's local environment** only.
4. All private strategy data and credentials remain local or behind the
   authenticated, authorized private bridge. Public-demo isolation passes.
5. Vercel resource availability, deployment quotas, and the effect on
   all Vercel projects are reviewed, including any shared deployment burst.
6. A verified commit SHA and rollback point exist. Explicit owner approval
   is obtained before creating one production deployment.

At that point, either deploy the exact tested revision manually through
the dashboard/CLI or deliberately re-enable `git.deploymentEnabled` as
part of the approved release, then set it back to `false` once published.
Never silently disable this freeze to make routine changes appear live.

## Vercel Hobby assessment

Hobby has a shared limit of 100 deployments per rolling 24 hours and
nine projects is far below its 200-project allowance. It also has
traffic, bandwidth, CPU, function, and Edge Config allowances that
aggregate at the team level. Our recent deployment spike came
overwhelmingly from Trading Simulator code pushes, not evidence of high
visitor traffic.

Static UI projects are generally suitable for small-scale personal
use. The higher resource risks are repeated CookieQuant telemetry
requests and Smart Irrigation API function or database usage.
Accurate current monthly per-resource consumption could not be obtained
from the available account metrics; review the Vercel team Usage page
before claiming ample headroom. Hobby is for noncommercial personal
usage, not unrestricted commercial production services.

The goal is to reduce deployment creation to **one intentional release
per real milestone**, and keep expensive compute on the appropriate
local or external infrastructure.
