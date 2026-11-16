# AI Strategy Assistant (v0.9)

The **AI Strategy Assistant** is available in single-asset Trading Arcade and
multi-asset Portfolio Arcade, directly next to the strategy editor.

Ask natural-language questions in **English or 简体中文**:

- "Suggest a conservative SMA crossover for SPY."
- "Analyze my strategy, fees, drawdown, and benchmark gap."
- "Why did my strategy underperform buy-and-hold?"
- "Give me a simple SPY signal to trade QQQ."
- "解释我现在的策略为什么会亏损。"
- "给我一个 SPY 的均线交叉策略。"

A connected language model reads a compact, server-generated report containing
**only historical data already revealed by your current game**. It can explain
metrics or suggest trading rules for your current basket. It is not connected to
a broker or to the internet beyond the explicitly chosen AI provider.

## Troubleshooting slow or timed-out Ollama responses

The original local Ollama integration had a 45-second response timeout. It
now uses a **240-second read timeout** by default, configurable via
`TRADING_SIM_AI_TIMEOUT_SECONDS` in `.env` (60-600 seconds). The local
development proxy also accepts long-running requests.

The UI shows elapsed processing time, and the backend requests a shorter
reply while keeping the model loaded for 20 minutes where Ollama supports it.

If your computer cannot run Llama 3.2 3B quickly, use its smaller local model:

```powershell
ollama pull llama3.2:1b
```

Then edit your ignored `.env`:

```dotenv
TRADING_SIM_AI_PROVIDER=ollama
TRADING_SIM_AI_MODEL=llama3.2:1b
TRADING_SIM_AI_TIMEOUT_SECONDS=240
```

Restart the backend, and use the assistant's **Recheck AI** control.
This remains completely local; no OpenAI API or per-request charges.

## First-time setup: local Ollama (default)

This option is free to use locally, with no remote model API required.

1. Install [Ollama](https://ollama.com/download) on the Windows computer.
2. In PowerShell, run `ollama pull llama3.2`. Start Ollama and make sure
   its local service responds on `127.0.0.1:11434`.
3. In your Trading Simulator folder, create a private config file:
   `Copy-Item .env.example .env`.
4. Leave `TRADING_SIM_AI_PROVIDER=ollama` and
   `TRADING_SIM_AI_MODEL=llama3.2` in `.env`, or choose another Ollama
   model you have already downloaded.
5. Start the existing Trading Simulator launcher:
   `powershell -ExecutionPolicy Bypass -File .\start-local.ps1`.
   If the backend was already running, close its existing backend window
   and restart it so it reads the new settings. The launcher intentionally
   avoids launching a second server on occupied port 8000.

Open a **saved Arcade season** to see the assistant. It needs actual game
data to discuss historical performance. A connected model is required to
answer questions: the UI does not pretend its preset prompt buttons are AI.

## Alternative: OpenAI API

You can choose the official OpenAI Responses API. This sends a **small
summary of your revealed game history** to OpenAI only when you ask a
question. It may have API usage charges and requires a separate OpenAI API key,
not merely a ChatGPT subscription.

Update your private `.env` file:

```dotenv
TRADING_SIM_AI_PROVIDER=openai
TRADING_SIM_AI_MODEL=gpt-6-luna
OPENAI_API_KEY=your_actual_api_key_here
```

Restart the backend. Keys are read by the Python process and are NEVER sent to
the browser, checked into Git, or returned in API responses. The backend
requests `store: false` from the OpenAI Responses API. Provider-specific
retention and privacy still depend on the provider's policies.

The fixed supported endpoints are:

- Ollama: `http://127.0.0.1:11434/api/chat`
- OpenAI: `https://api.openai.com/v1/responses`

Arbitrary user-supplied URLs are never accepted, to avoid turning the local
backend into a network proxy. The assistant does not access exchange APIs
or query future prices.

To turn AI off, set `TRADING_SIM_AI_PROVIDER=off`.

## What the assistant can use

It reads existing server-side reports for the selected saved game:

- Basket IDs, candle resolution, current replay timestamp, current strategy
  and risk controls
- Current positions and approximate mark-to-market values
- Current equity, return, drawdown, fees and benchmark comparison
- Rolling returns, instrument attribution and at most 8 recent executions

The model cannot access the entire hidden provider snapshot, all future
market bars, broker account credentials, trade authorization, or your
machine's other files. At most six recent chat messages accompany a new
question, within strict request limits.

## Human review is mandatory

When the model suggests code, the backend compiles its output using the
existing safe grammar before returning it. Rules must reference symbols in
your current game. Unsupported syntax, programming code and arbitrary
asset identifiers are rejected.

You can click **Insert draft for review** to copy validated code into the
strategy editor. This action does **not** save the strategy, run a backtest,
arm a bot, advance the market or submit an order.

To use it, read the proposal and manually click the separate **Save & arm
bot** button in the Arcade editor. Even valid syntax does **not** mean the
strategy has been backtested or has a high expected return.

**Portfolio sizing caveat:** `BUY 50%` means half the *remaining cash*
at fill time, rather than a fixed 50% portfolio target. An AI response
must not promise simultaneous 50/50 allocation or risk-free performance.

## API and developer notes

- `GET /api/ai/status`: returns selected provider and model information,
  not credentials. For Ollama it probes localhost for the selected installed
  model; this does not guarantee all later inference requests will succeed
- `POST /api/ai/ask`: accepts `mode` (`single` or `portfolio`),
  `run_id`, `question`, and up to 6 short history entries
- `backend/ai_assistant.py`: safe read-only orchestration and DSL validation
- `src/AIAssistant.tsx`: bilingual chat with explicit draft review
- `backend/tests/test_ai_assistant.py`: offline provider/privacy/validation tests

No new frontend or backend dependencies are needed. All existing SQLite saves,
financial calculations, and historical data caches remain unchanged.
