import type { Asset, AssetClass } from "../types";

export const INITIAL_CASH = 100_000;
export const ASSET_CLASSES: AssetClass[] = ["Stocks", "ETFs", "Options", "Futures", "Forex", "Crypto", "Indices", "Funds"];

export const ASSETS: Asset[] = [
  { id: "aapl", symbol: "AAPL", name: "Apple Inc.", exchange: "NASDAQ", assetClass: "Stocks", decimals: 2, spreadBps: 6, accent: "#a3b4cd" },
  { id: "nvda", symbol: "NVDA", name: "NVIDIA Corp.", exchange: "NASDAQ", assetClass: "Stocks", decimals: 2, spreadBps: 8, accent: "#8ce6a9" },
  { id: "tsla", symbol: "TSLA", name: "Tesla Inc.", exchange: "NASDAQ", assetClass: "Stocks", decimals: 2, spreadBps: 12, accent: "#ef8f82" },
  { id: "msft", symbol: "MSFT", name: "Microsoft Corp.", exchange: "NASDAQ", assetClass: "Stocks", decimals: 2, spreadBps: 5, accent: "#8bbaff" },
  { id: "spy", symbol: "SPY", name: "SPDR S&P 500 ETF", exchange: "NYSE ARCA", assetClass: "ETFs", decimals: 2, spreadBps: 3, accent: "#8bbaff" },
  { id: "qqq", symbol: "QQQ", name: "Invesco QQQ Trust", exchange: "NASDAQ", assetClass: "ETFs", decimals: 2, spreadBps: 4, accent: "#c3a4ff" },
  { id: "vfv", symbol: "VFV.TO", name: "Vanguard S&P 500 ETF", exchange: "TSX", assetClass: "ETFs", decimals: 2, spreadBps: 8, accent: "#67c6b2" },
  { id: "aapl-opt", symbol: "AAPL 200C", name: "Example call option", exchange: "OPRA · illustrative", assetClass: "Options", decimals: 2, spreadBps: 120, accent: "#eacb8e" },
  { id: "spy-opt", symbol: "SPY 500P", name: "Example put option", exchange: "OPRA · illustrative", assetClass: "Options", decimals: 2, spreadBps: 150, accent: "#eacb8e" },
  { id: "es", symbol: "ES=F", name: "E-mini S&P 500 continuous (Yahoo proxy)", exchange: "CME · indicative", assetClass: "Futures", decimals: 2, spreadBps: 2, accent: "#88b7f6" },
  { id: "nq", symbol: "NQ=F", name: "E-mini Nasdaq continuous (Yahoo proxy)", exchange: "CME · indicative", assetClass: "Futures", decimals: 2, spreadBps: 3, accent: "#d9a3f0" },
  { id: "eurusd", symbol: "EUR/USD", name: "Euro / US Dollar", exchange: "FX · indicative", assetClass: "Forex", decimals: 5, spreadBps: 2, accent: "#8fcba5" },
  { id: "gbpusd", symbol: "GBP/USD", name: "British Pound / US Dollar", exchange: "FX · indicative", assetClass: "Forex", decimals: 5, spreadBps: 3, accent: "#d5a2bc" },
  { id: "btcusd", symbol: "BTC/USD", name: "Bitcoin / US Dollar", exchange: "Crypto · illustrative", assetClass: "Crypto", decimals: 2, spreadBps: 20, accent: "#f5b969" },
  { id: "ethusd", symbol: "ETH/USD", name: "Ethereum / US Dollar", exchange: "Crypto · illustrative", assetClass: "Crypto", decimals: 2, spreadBps: 22, accent: "#a5adf2" },
];


export function formatPrice(value: number, decimals = 2) {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: decimals, maximumFractionDigits: decimals,
  });
}

export function formatMoney(value: number) {
  return value.toLocaleString("en-US", {
    style: "currency", currency: "USD",
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}
