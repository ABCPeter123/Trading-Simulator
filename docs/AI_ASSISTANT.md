# AI Strategy Assistant (v1.0)

The **AI Strategy Assistant** is available in single-asset Trading Arcade and
multi-asset Portfolio Arcade as an expandable floating panel in the bottom-right corner. It keeps the editor clear until opened.

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

## Windows local TwIL / Qwen router setup

Run both GGUF models from `models/private/` using llama.cpp's loopback-only
router. The installed router can advertise **model stems**, not the full
`.gguf` filenames. The API validates both representations against
the configured allowlist and sends router-compatible model names.
For availability, it queries **GET `/models`**, which includes installed
but unloaded models. The OpenAI-compatible **GET `/v1/models`** endpoint
can be empty until inference first loads a model and is only a fallback.
If the assistant says no models are available, compare these endpoints
before reinstalling any weights:

```powershell
(Invoke-RestMethod http://127.0.0.1:8081/models).data | Select-Object id,status
Invoke-RestMethod http://127.0.0.1:8000/api/ai/status
```

`ready: true` means the chosen model is present and selectable, while
`loaded: false` is normal until the router loads it for its first request.
`connection_state` distinguishes an unreachable server from an empty model
inventory or an unapproved selection.

Example local `.env`:

```dotenv
TRADING_SIM_AI_PROVIDER=llama_cpp
TRADING_SIM_AI_MODEL=TwIL-8B-Q4_K_M-balanced.gguf
TRADING_SIM_AI_MODELS=TwIL-8B-Q4_K_M-balanced.gguf,Qwen3.5-9B-Q4_K_M.gguf
TRADING_SIM_AI_TIMEOUT_SECONDS=600
TRADING_SIM_AI_MAX_OUTPUT_TOKENS=8192
```

`start-local.ps1` now starts background API, Vite, market collection, research
worker and, if installed and needed, a loopback-only llama.cpp router without
opening new visible PowerShell windows. It reuses an already running router.

```powershell
cd E:\Trading-Simulator
.\stop-local.ps1
.\start-local.ps1
```

The stop script manages services launched by the new launcher only.
Close terminals from older launcher versions manually once. Diagnostics
stay private under `.local-state/logs/`. The backend must restart after
changing local `.env` because a Vite refresh cannot change server environment
variables.

When status reports `connection_state: unreachable`, the models may be
installed but **llama-server is not reachable on port 8081**. The launcher now
checks that a freshly started router responds and shows the last lines of its
local logs if startup fails. The AI panel retries its status while offline.

To diagnose without printing environment variables or private trading data:

```powershell
.\scripts\diagnose-local-ai.ps1
Get-Content .\.local-state\logs\ai.err.log -Tail 30
```

If there is no listening server and the launcher cannot find the executable,
check `Get-Command llama-server`, open a fresh terminal after installing
llama.cpp, or reinstall its executable. If you started the router manually,
keep that process open or rerun `.\start-local.ps1 -NoBrowser` to let the
launcher start it quietly. Neither step requires restarting the FastAPI
backend if its `.env` already selects `llama_cpp`.

From a saved simulation, click the AI button in the lower-right corner to
expand or collapse the chat. Select TwIL or Qwen directly in the panel. The
assistant is still read-only and generates draft DSL for separate review.
The button only appears when an applicable saved research simulation is open.

The llama.cpp server must stay on `127.0.0.1:8081`; do not expose an
unauthenticated AI router on a public interface or tunnel.

## Running faster on 16 GB RAM Windows

The local launcher defaults to the **speed** profile: 4096-token context,
512/256 prompt batch limits, one loaded model, and single-query parallelism.
Generation threads default to physical CPU cores (up to 12), while prompt
batch threads can use up to 16 logical processors. The server asks llama.cpp
to offload GPU layers automatically and use flash attention where supported.
A CPU-only llama.cpp build cannot use the GPU merely through command flags.

Add these to your existing Git-ignored local .env:

~~~dotenv
TRADING_SIM_LLAMA_PROFILE=speed
TRADING_SIM_LLAMA_GPU_LAYERS=auto
TRADING_SIM_AI_MAX_OUTPUT_TOKENS=4096
# Optional manual overrides:
# TRADING_SIM_LLAMA_THREADS=8
# TRADING_SIM_LLAMA_THREADS_BATCH=12
# TRADING_SIM_LLAMA_CONTEXT=6144
# TRADING_SIM_LLAMA_BATCH=1024
# TRADING_SIM_LLAMA_UBATCH=256
~~~

Available profiles are speed (4096 context, 512/256 batch),
balanced (6144 context, 1024/256 batch) and quality (8192 context,
1024/512 batch). All profiles use --models-max 1 and --parallel 1,
so both models remain installed but only one is loaded.

Long reasoning models may consume their entire output budget while
thinking. Reduce the budget for faster everyday answers, and raise it
again for long tasks that need more reasoning. A smaller limit can cause
an incomplete response and does not guarantee higher tokens/second.

~~~powershell
cd E:\Trading-Simulator
git pull
.\stop-local.ps1
.\start-local.ps1 -NoBrowser
.\scripts\diagnose-local-ai.ps1
~~~

The launcher reuses any existing listener on port 8081, so it cannot
change settings of a llama.cpp process that was started manually. Close
that manual process before starting the tuned router.

Check actual GPU hardware and llama.cpp backend support:

~~~powershell
nvidia-smi
llama-server --list-devices
~~~

GPU offload improves speed only if the installed llama.cpp binary includes
a compatible hardware backend. If --list-devices shows only CPU, install
a GPU-enabled llama.cpp build appropriate for your GPU before expecting
acceleration. CPU thread counts also require benchmarking: more threads
than physical CPU cores can be slower.

The E: drive stores model weights and may improve cold model loads if it
is an SSD. llama.cpp normally memory-maps model files. A Windows page
file on a fast SSD can avoid an out-of-memory crash, but active paging
is far slower than physical RAM and usually reduces tokens/second.
Do not force KV cache to disk as a speed optimization. No Windows
virtual-memory settings are changed automatically.

## Legacy: troubleshooting slow or timed-out Ollama responses

The original local Ollama integration had a 45-second response timeout. It
now uses a **240-second read timeout** by default, configurable via
`TRADING_SIM_AI_TIMEOUT_SECONDS` in `.env` (60-600 seconds). The local
development proxy also accepts long-running requests.

The UI shows elapsed processing time. Opening the website triggers a non-blocking
local preload through `POST /api/ai/warmup`, and Ollama is asked to keep the
selected model loaded for 30 minutes. Status indicates whether loading is
underway. Startup requests retry if the backend starts later than the frontend.

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

## Better local model quality

The bundled default `llama3.2` is small, so detailed financial analysis
can remain weak even with better prompts. For stronger English and Chinese
reasoning, choose a larger locally installed model if your PC has adequate RAM.
For example:

```powershell
ollama pull qwen2.5:7b
```

Set these values in your existing ignored `.env` file, then restart the
Python backend:

```dotenv
TRADING_SIM_AI_PROVIDER=ollama
TRADING_SIM_AI_MODEL=qwen2.5:7b
```

This downloads several GB and requires additional memory. It remains local
and has no per-request API fee. Smaller models may run faster, but often
produce weaker reasoning. You can revert to `llama3.2` at any time.

The assistant now receives a system prompt describing strategy grammar,
quantitative evidence checks, benchmark comparisons, risk, sizing, and
limitations. It also receives up to 24 **revealed-only** equity/benchmark
observations, current positions and exposure, rolling results, and the last
12 executions. It answers in your selected interface language even if your
question uses the other language. It cannot inspect unrevealed candles.

## Optional TwIL-8B by webAI, local llama.cpp

The repository already supports a fixed loopback-only llama.cpp adapter.
TwIL-8B is an **8.79 billion parameter English-language reasoning model**
from [webAI](https://huggingface.co/webAI-Official/TwIL-8B), based on IBM
Granite 4.2 8B. The default balanced Q4_K_M GGUF is approximately 4.98 GiB.
The model card lists strong math and coding scores but weaker knowledge
benchmarks. Its reported results were measured mainly in BF16 with long
reasoning budgets; quantized, shorter runs may behave differently.

**License:** The weights use the **webAI Non-Commercial License v1.0**, not
an unrestricted commercial license. Confirm that your intended use is
permitted before using the model in any commercial service. This model
is not automatically downloaded, bundled, served by Vercel, or hosted
by Trading Simulator.

Download and run locally with a recent llama.cpp build, using PowerShell:

```powershell
llama-server -hf webAI-Official/TwIL-8B --hf-file TwIL-8B-Q4_K_M-balanced.gguf --host 127.0.0.1 --port 8081 -c 16384 -n 8192
```

Set the following in the **Git-ignored** local `.env`:

```dotenv
TRADING_SIM_AI_PROVIDER=llama_cpp
TRADING_SIM_AI_MODEL=TwIL-8B-Q4_K_M-balanced.gguf
TRADING_SIM_AI_TIMEOUT_SECONDS=600
TRADING_SIM_AI_MAX_OUTPUT_TOKENS=8192
```

Restart the local FastAPI backend and select **Recheck AI**.
The backend probes `http://127.0.0.1:8081/v1/models` and sends chat
requests to the corresponding loopback chat-completions endpoint. It will
not start the server automatically. Longer thinking contexts use more RAM,
take more time, and can time out, especially on CPU. The requested
output-token budget is only a ceiling and does not guarantee a complete
response. TwIL produces a reasoning preamble that the API strips before
display, and suggested strategy rules still undergo server-side validation.

For Simplified Chinese explanations, prefer a multilingual local model
such as Qwen. TwIL's model card lists **English** as its language.
No model receives credentials or authority to place trades.

## Legacy first-time setup: local Ollama (optional)

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
- Rolling returns, instrument attribution and at most 12 recent executions plus 24 observed curve checkpoints

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
- `POST /api/ai/warmup`: starts a non-blocking, idempotent model preload on localhost only
- `POST /api/ai/ask`: accepts `mode` (`single` or `portfolio`),
  `run_id`, `question`, optional `language`, and up to 6 short history entries
- `backend/ai_assistant.py`: safe read-only orchestration and DSL validation
- `src/AIAssistant.tsx`: bilingual chat with explicit draft review
- `backend/tests/test_ai_assistant.py`: offline provider/privacy/validation tests

No new frontend or backend dependencies are needed. All existing SQLite saves,
financial calculations, and historical data caches remain unchanged.
