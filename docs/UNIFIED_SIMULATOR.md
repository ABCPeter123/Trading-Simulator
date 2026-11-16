# Unified Trading Simulator and Strategy Library (v1.1)

The previous standalone Trading Terminal has been consolidated into one
**Trading Simulator** interface. There is no separate terminal screen or
navigation destination. The historical single-asset simulator is the default
home, with a button to enter the portfolio mode.

## Navigation

The main workspace now includes:

- **Historical Replay**: historical candles, SMA overlays, replay controls
- **Market Data & Paper**: original terminal functionality, including
  watchlists, asset categories, delayed quotes, candlestick/line charts,
  account balances, manual simulated cash orders, pending replay trades,
  historical local replay, SMA backtesting, position details, fills and
  portfolio history
- **Orders & Positions**: historical replay execution ticket, risk limits
  and pending orders
- **Strategy & AI**: rule builder, editable DSL strategies, AI assistance
  and the new saved strategy library
- **Performance Analytics**: equity, benchmarks, drawdowns, execution
  audit and CSV exports
- **Scenario Research**: reproducible 256-path stochastic simulations,
  forecast-aware rule examples and European Black-Scholes calculator
- **Trade History**: execution and event history

Inside **Market Data & Paper**, the original market/paper research subviews
are retained as small local tabs so none of the original functionality is
lost. This is **not** a third app or a separate terminal entry point.

Paper account data remain independent of the replay accounts. The paper
ledger uses quotes and simulated execution rules; it does not send live
brokerage orders.

## Strategy library and previous versions

Open **Strategy & AI** and use **Saved Strategy Library** to:

1. Name and **Save current draft** without executing it.
2. Browse all named and automatically archived strategies for the selected
   single-asset or portfolio strategy type.
3. Expand a previous version and choose **Load into strategy editor**.
4. Inspect and edit the restored draft.
5. Explicitly click **Save & activate strategy** only when ready.
6. Delete an unused saved version without affecting the running strategy.

Each named save creates a **new immutable version** rather than overwriting
an existing entry. Changing the active strategy also archives the outgoing
strategy, if it was not archived already, and the new activated version.

Entries are persisted in the local SQLite database
`data/strategy_library.sqlite3`. The same saved library is available across
browser reloads and saved simulation sessions. Single-asset and portfolio
strategies remain distinct because their DSL grammars differ. A portfolio
strategy loaded from another basket may need edits to match the new basket
before activation.

Old existing saved game records and other account ledgers are not
overwritten or migrated.

Library API:
- `GET /api/strategies?mode=single|portfolio`
- `POST /api/strategies`, payload: name, mode, code, symbols, optional source_run_id
- `GET /api/strategies/{strategy_id}`
- `DELETE /api/strategies/{strategy_id}`

The backend verifies strategy code with the actual safe DSL compiler,
not with a language-model-generated suggestion.

## Ollama timeout fix

The AI assistant still defaults to **free local Ollama**. Previously,
the backend cut off responses after a 45-second timeout even when
the model was still processing. The local client now has a longer
default **240-second read timeout**, and retains the selected model
in memory for 20 minutes where supported.

Local responses have a smaller maximum output budget to improve latency.
The UI displays an elapsed time while the model processes. The Vite
development proxy also permits longer local requests.

You can adjust these settings in the private `.env` file:

```dotenv
TRADING_SIM_AI_PROVIDER=ollama
TRADING_SIM_AI_MODEL=llama3.2
TRADING_SIM_AI_TIMEOUT_SECONDS=240
```

The timeout may be set between **60 and 600 seconds**. Restart the
Python backend after editing `.env`.

If your CPU cannot serve the model quickly, you can use a smaller free
local model:

```powershell
ollama pull llama3.2:1b
```

Then change `TRADING_SIM_AI_MODEL=llama3.2:1b` in `.env` and restart
the backend. This does **not** require an OpenAI account, paid API key
or subscription.

Longer timeouts reduce false failures from slow local inference. They
cannot make slow hardware run a model faster, solve insufficient memory
or repair a stopped Ollama server. The app returns explicit errors
when a model fails, and it does not send requests to a paid AI provider
without your explicit remote-provider configuration.

## Run and validate

```powershell
git pull
powershell -ExecutionPolicy Bypass -File .\start-local.ps1
```

Your existing SQLite data and local `.env` settings remain intact.
No new frontend or Python dependencies are required.
