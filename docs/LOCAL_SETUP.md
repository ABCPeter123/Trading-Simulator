# Local development state: Trading Simulator

This file documents the default local setup we assume for this project.

- Platform: **Windows + VS Code + PowerShell**.
- Source code: cloned GitHub repository `ABCPeter123/Trading-Simulator`.
- Python environment: `.venv/`, created only once.
- Backend: `backend.main:app` on `http://127.0.0.1:8000`.
- Frontend: Vite on `http://127.0.0.1:5173`.
- Paper trades and cash: `data/trading.sqlite3`, retained between sessions.
- Historical prices: `data/market/`, retained between sessions.
- Node dependencies: `node_modules/`, retained between sessions.

These are **our intended setup conventions**, not a live inspection of your PC.
The assistant cannot observe your local installation from GitHub alone.

## Normal routine

After pulling an update, run this single Windows command from the repository:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-local.ps1
```

The launcher inspects the local files and skips installs when the dependencies
are already present and unchanged. It starts both development servers, or
leaves an already listening port alone.

To check/update dependencies **without** launching anything:

```powershell
powershell -ExecutionPolicy Bypass -File .\start-local.ps1 -SetupOnly
```

To run the servers manually (no dependency installation):

```powershell
# VS Code terminal 1
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
```

```powershell
# VS Code terminal 2
npm run dev
```

## What is persisted and what isn't

The launcher records local dependency fingerprints in the ignored
`.local-state/` folder. Existing installs are reused; Python or Node packages
are installed if missing or after a tracked dependency manifest changes.

The script does **not** call `git pull` automatically, overwrite your database,
erase your historical market data, or modify your Python interpreter globally.

**Do not rerun** `py -3 -m venv .venv`, `pip install -r`, or
`npm install` every session. Only use these commands manually when the
corresponding dependencies are missing or need updating.

For future assistant changes: Assume the developer has cloned this repository,
initialized `.venv` and `node_modules`, and already installed earlier
dependencies. Identify *new or changed* dependencies explicitly. Avoid
repeating full bootstrap steps unless necessary.
