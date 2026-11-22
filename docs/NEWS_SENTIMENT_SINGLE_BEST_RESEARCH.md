# Free news and single-best practical strategy research

This feature remains local-first. GitHub contains only generic algorithms and independently synthetic tests. Owner headlines, private signals, selected strategy parameters, actual reports and holdings remain on the user's machine in Git-ignored storage.

## Free GDELT news

`GET /api/live/research/news/sentiment?symbols=spy,qqq` reads local SQLite headline records. `POST /api/live/research/news/refresh`, body `{"symbols":["spy","qqq"]}`, fetches up to five instrument queries from the free, keyless GDELT DOC 2.0 article list. Requests use 15-minute local refresh throttling, a finite headline count and deliberate pacing between queries. Failures report unavailable data, never synthetic news. News ingestion is not allowed in public-demo mode.

**Provenance and no look-ahead:** the system stores the article publication date and the earliest time the local machine actually saw the article. A signal can read a headline only after both timestamps, never simply because the publisher later claims an earlier time. The collector does not overwrite earlier observation timestamps and never writes headlines into existing daily backtests. GDELT's online searchable article window is limited, and coverage may vary, particularly for Canadian tickers, ETFs, ambiguous company names and non-English news. There is no manufactured historical headline archive.

Headline scores use a transparent English **financial event keyword heuristic** (profit and earnings beats, guidance, major contracts, lawsuits, downgrades, etc.) with recency weighting. This is NOT yet TF-IDF/Ridge training, calibrated probabilities, proof of sentiment direction or a validated return forecast. Headline direction and source remain inspectable. False or irrelevant match, duplicated stories and media bias can affect scores. Positive scores cannot create leveraged or short paper exposure.

An opt-in **news-risk overlay** is available when creating a NEW walk-forward forward-paper study. The local private live worker automatically refreshes a bounded rotating sample of no more than five ticker queries per cycle when at least one active opted-in paper study exists, with per-symbol cache throttling. A manual refresh is also available in the Research Lab without first running a tournament. This requests only public instrument search terms from GDELT, never holdings, financial accounts, allocation weights or private strategy reports. It reduces the selected long-only weights by at most 35% on negative locally observed headlines, retains unused cash and leaves nonnegative/unknown scores unchanged. The default remains OFF. The feature does not revise an existing frozen study and never submits brokerage orders. Evaluate the overlay against an independent no-news control over genuinely new observations before enabling it for any actual decisions.

## Why the AlgoArena Sharpe cannot be copied directly

The recovered AlgoArena baseline code and research protocol predicted the market-adjusted return from **bar 49 to bar 59**, based on the first 50 bars plus timestamps and headline text visible by bar 49. The competition scored

`sqrt(252) * mean(position * market_adjusted_return) / std(position * market_adjusted_return)`

over separate synthetic sessions. It allowed positive and negative positions without the real cash ledger's margin, share borrow, market impact, spreads, currency conversions or tax payments. The listed cost sensitivities were hypothetical and not in the official score. The challenge's ordered sessions also were not proven to be chronological real market sessions. The recovered model used TF-IDF text ngrams, short- and long-horizon price features, training-only preprocessing and Ridge regression. It optimized signal thresholds and volatility-based size on expanding blocked validation, with a final audit separated from tuning.

**Transferable principles:** timestamp-safe features; time-aware validation; model selection on per-position PnL Sharpe; signal strength and realized volatility for sizing; zero-signal abstention; measurement of fold-to-fold stability and baseline comparison. A high competition Sharpe is not an annual excess Sharpe in a funded, taxable, manually traded real-world portfolio, and it does not establish expected profitability.

At present the simulator's news scores are a *prospective experiment*, not a historically trained event-return predictor, because no verified point-in-time headline dataset with suitable multi-year market labels is installed. A separate, subsequently time-verified archive plus walk-forward training and genuinely fresh audit is required before integrating predictive sentiment as a selected historical strategy factor.

## One practical candidate instead of model buckets

A new universe scan searches candidate models and baskets internally, but returns **a single highest-ranked eligible manually cash-executable portfolio** or explicitly returns no qualifying candidate. There is no per-family quota and no forced group/diversity representation. Only training and validation data can affect screening or selection; the sealed last 20% stays out of ranking. Historic scans preserve their original results.

The practical validation score prioritizes **excess Sharpe**, while penalizing drawdown, turnover, adverse delayed fill performance, underperformance against same-basket equal weight, account-operation complexity and FX dependence. Original backtest equity already reflects configured commissions, FX, spreads, borrow/funding where applicable. Selection excludes share shorts, direct share leverage and several highly leveraged or inverse ETF proxies from the simple cash-tradable result. This exclusion is about execution feasibility, not whether those concepts are valid research subjects. Paper and research modes still exist separately.

A configurable positive-realized-gain **tax reserve sensitivity** defaults to an assumed 25% effective rate, with allowed values from 0% to 50%. It approximates average-cost basis and multiplies only positive realized sale gains; it deliberately does not claim legal tax liability or net taxes against the equity curve, does not model tax loss netting, the Canadian inclusion rate, distributions, other income, TFSA/RRSP rules or trading/business income classifications. The appropriate rate depends on account and individual facts. Setting 0 allows tax-free scenario comparisons. Actual broker availability, eligibility, order-entry complexity, conversion spreads, funding currency and true historical dividend-adjusted returns remain unverified. Investment eligibility and tax statements require independent confirmation.

The selected candidate is **research only** until walk-forward and new forward-paper evidence supports it. High scores or historical excess Sharpe do not guarantee it beats a passive benchmark in the future.
