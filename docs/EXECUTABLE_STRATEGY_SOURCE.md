# Executable strategy source

The portfolio strategy language is **Python 3**, using the existing backend as
the canonical interpreter. A strategy version's JSON specifies which Python
allocation function to run and its input parameters. JSON is not executable
strategy code, and the old pseudocode panel was only a verbal approximation.

## Where exact decisions execute

| Context | Allocation | Execution and accounting |
| --- | --- | --- |
| Tournament research, models v1 | \`backend.portfolio_research._weights\` | \`backend.portfolio_research._segment\` |
| Tournament research, models v2 | \`backend.advanced_portfolio_research.weights\` | \`backend.advanced_portfolio_research.segment\` |
| Historical replay | Same selected allocation function | \`backend.portfolio_arcade._rebalance_model\`, \`advance\`, \`_execute\` |
| Paper/live monitoring | Same selected allocation function | \`backend.live_machine._evaluate_portfolio_model\` and \`run_once\` |

All of these functions execute inside the application's own Python package.
They depend on shared modules, instrument metadata, actual historical market
bars and the private model configuration. Pasting a single allocation function
into a blank Python file is **not** an equivalent standalone backtest.

The Strategy Inspector loads the running backend's **actual function sources**
with line numbers and SHA-256 hashes; the **Complete executable Python modules**
section contains entire original modules, including imports and helper code.
It does not synthesize, translate or reconstruct strategies. Each model is
selected by a versioned JSON configuration, and models share functions with
different branches selected by the model string.

A source snapshot reflects the server process and its local checkout. Restart
the Python backend after changing a module. If the local backend is not running,
the UI shows an error instead of substituting fabricated code.

## Private read-only API

\`POST /api/live/research/universe/strategy-source\`

JSON body: \`{"spec": <versioned portfolio model configuration>, "context": "research"}\`

The context can also be \`simulation\` or \`live\`. The request is allowed only
on the private engine. It is rejected in public demo mode. No submitted
configuration, strategy results, historical data or account information is
written into the repository by this API. The response intentionally contains
the generic source code, not the submitted private basket or weights. Never
upload private requests, replies, logs, tests, CI fixtures or screenshots to
a public repository.

## Editing and testing

To change a **built-in** allocation algorithm, edit the relevant Python
module, and re-run the existing synthetic backend tests before using it. A
model's rule implementation and the strategy version stored in the library are
not the same thing. Changing the implementation alters what an existing model
name means, so before deploying real strategy versions, introduce a new,
explicit version and verify historical reproducibility.

Use these local checks:

\`\`\`powershell
npm run typecheck
npm run verify:local
.\.venv\Scripts\python.exe -m pytest backend\tests -q
\`\`\`

Saved actual strategies and results remain in Git-ignored private storage.
No source-inspection request sends a broker order. Signed short positions and
borrowed/margined strategies remain research-only unless and until a separate,
explicitly validated live execution path exists. This feature does **not** add
arbitrary Python execution through the browser or claim identical backtest,
replay and live fill prices.

The local-first release policy remains in force. Git commits and CI do not
authorize a Vercel production deployment.
