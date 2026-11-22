# Historical news sentiment: free daily GDELT backfill, 2013 onward

## Source and scope

- **Provider:** GDELT Global Knowledge Graph 1.0 public daily archive, beginning April 1, 2013. Source: https://gdeltproject.org/data.html and historical file listing: https://data.gdeltproject.org/gkg/index.html
- **No API key or paid service:** daily `YYYYMMDD.gkg.csv.zip` downloads via HTTPS from `data.gdeltproject.org/gkg/`.
- **Not the recent DOC API:** GDELT DOC article-headline searches only cover a much shorter practical search window. The daily historic GKG files give **aggregate nameset tone** and organization mention counts. They do not contain the recent DOC API's headline text or a clean per-article sentiment label. They cannot reproduce an AlgoArena TF-IDF headline experiment.
- **Coverage:** dated archives exist from 2013 onward, but archive availability, organization matching and individual file integrity can vary. The first year is not necessarily comparable with the present. GKG nameset organization mentions are not a clean ticker/entity identifier.
- **Stock only for now:** avoid attributing general market news to ETF ticker names without validated entity mapping. Company names and a limited transparent alias catalog identify organization mentions, including Nvidia, Tesla, Apple, Microsoft and others.

## Local workflow

Open **Research Lab → Strategy Tournament → Free news sentiment → Older news archive**. Choose stock symbols (up to five), an ISO start and end date, and click **Queue historical download**. Dates may be from April 1, 2013 through two calendar days before now. Each job accepts 1–31 calendar days. Jobs are durable and progress one archive day at a time in the private research worker. After completing, use **View locally archived dates** to inspect actual daily coverage, aggregate tone, matched namesets, approximate article mentions and the conservative research availability time. Repeat adjacent batches to build multi-year coverage.

A recent GKG archive can exceed 30MB compressed each day. A 31-day request could therefore require roughly 1GB of transfer or more. The worker downloads one fixed HTTPS archive per calendar day, caps downloads at 80 MiB, caps expanded ZIP size at 900 MiB, parses without loading the expanded graph into memory, retains only small per-company daily aggregates in local SQLite and discards the source ZIP. The private research worker does not publish these outputs to GitHub or Vercel. Missing or malformed archives cause explicit job failure. A new job for an overlapping period skips complete previously archived symbol-days. A cancelled job leaves completed data intact.

## Historical timestamp discipline

The original GKG date denotes the **news publication day**, but the aggregated daily export is produced the following morning. To be conservative, the simulator records a fixed **D+2, 09:30 New York** earliest research availability for daily tone dated D. Historical research may use day D's tone at or after this cutoff, never at D itself. Missing exact eligible archive dates remain **missing**, never extrapolated from other dates or replaced by zero. The local GKG backfill date is NOT stored as a fake live observation time.

The existing `backend/news_sentiment.py` live pipeline uses its own `first_observed_utc` for actual collected DOC headlines. It never consults GKG historical backfills. Backfilled data cannot change an already frozen paper-forward study or real-time alert. `historical_news.historical_score_at(symbol, decision_utc)` is explicitly research-only and enforces the availability cutoff.

## Scoring and limitations

For each dated GKG 1.0 nameset, the parser reads `DATE, NUMARTS, COUNTS, THEMES, LOCATIONS, PERSONS, ORGANIZATIONS, TONE, CAMEOEVENTIDS, SOURCES, SOURCEURLS`. The total archive is a full daily export, not a selected 15-minute sample. For each matched company, it weights GKG's nameset tone by `NUMARTS` (document mentions), aggregates all matches for that calendar day, and normalizes by dividing the mean tone by 10, clamping to [-1,+1]. This normalized value is a **heuristic data feature**, not a calibrated forecast. GKG 1.0 groups articles into namesets; mentions can be affected by duplicates and article grouping, and the tone is not necessarily company-specific even when a company is mentioned in a negative article.

These historical observations have **not** been included in portfolio optimizer validation, and no improved Sharpe or reduction in drawdown has been demonstrated. A separate leakage-controlled experiment should train and select a sentiment-return model with date-aware folds, matching daily bar execution to the D+2 availability lag, then compare cost-adjusted OOS Sharpe and drawdown against the exact same strategy without the sentiment feature. Do not treat historical backfill as live evidence or reuse the final audit for feature selection.

## Private endpoints

- `POST /api/live/research/news/history/jobs`: JSON `{"symbols":["nvda"],"start_date":"2020-03-01","end_date":"2020-03-07"}`
- `GET /api/live/research/news/history/jobs` and `GET /api/live/research/news/history/jobs/{job_id}`
- `POST /api/live/research/news/history/jobs/{job_id}/cancel`
- `GET /api/live/research/news/history?symbols=nvda&start_date=2020-03-01&end_date=2020-03-07`

All endpoints inherit the private-engine access controls. There is no public archive of personal backfilled records. Tests use independent synthetic ZIP contents and never fetch public GDELT data in CI.
