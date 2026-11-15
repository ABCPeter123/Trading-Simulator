# Trading Simulator

A local-first, multi-asset paper-trading terminal. The first milestone is a functional display foundation with **synthetic demo candles**, a responsive chart, watchlists, and a simple local demo order ledger. No market-data provider, live feed, or real-money broker is connected yet.

## Stack

- React 19 + TypeScript + Vite
- TradingView Lightweight Charts v5 for price/volume charts
- Lucide React for interface icons
- Local browser storage for **demo-only** orders (no backend required)

## Run locally

1. Install Node.js 22 or newer.
2. Run:

```bash
git clone https://github.com/ABCPeter123/Trading-Simulator.git
cd Trading-Simulator
npm install
npm run dev
```

3. Open the local URL printed by Vite, usually http://127.0.0.1:5173.

### Scripts

```bash
npm run dev       # start the local UI
npm run typecheck # validate TypeScript
npm run build     # production build for verification
npm run preview   # preview the build locally
```

## Implemented

- Multi-asset watchlist: stocks, ETFs, options, futures, forex, and crypto
- Searchable symbol navigation
- Candlestick and line charts with volume and selectable time ranges
- Synthetic, reproducible OHLCV demo series (clearly marked)
- Demo-only buy/sell market-order form with simulated bid/ask spread
- Basic long-only cash portfolio, positions, history, and reset
- Demo state persisted in this browser using localStorage
- Desktop and mobile-responsive dark terminal layout

## Not yet implemented

- Actual market data, market sessions, contract reference data, execution fidelity, real-time prices, fees, margin/short sales, historical replay, backend, or authentication
- Futures contract multipliers, options expiration/exercise/greeks, forex funding, and crypto settlement
- A realistic fill model and strategy/backtesting engine

**All prices, charts, spreads, and trades are synthetic. Do not use this milestone for investment decisions or performance evaluation.** The toy order ledger is useful only to exercise the display and local state before the proper simulation engine is developed.

## Next architecture steps

1. Introduce market-data adapters, keeping provider licensing in mind.
2. Add an event-driven replay engine behind a Python FastAPI service.
3. Persist orders and positions in local PostgreSQL and market data in local Parquet files.
4. Implement asset-specific execution rules and reproducible backtesting.

Charting by [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/).
