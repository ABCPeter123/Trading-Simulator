import type { UTCTimestamp } from "lightweight-charts";
import type { Asset, AssetClass, MarketSeries, TimeRange } from "../types";

export const INITIAL_CASH = 100_000;
export const ASSET_CLASSES: AssetClass[] = ["Stocks", "ETFs", "Options", "Futures", "Forex", "Crypto"];

export const ASSETS: Asset[] = [
  { id: "aapl", symbol: "AAPL", name: "Apple Inc.", exchange: "NASDAQ", assetClass: "Stocks", referencePrice: 188.42, decimals: 2, spreadBps: 6, accent: "#a3b4cd" },
  { id: "nvda", symbol: "NVDA", name: "NVIDIA Corp.", exchange: "NASDAQ", assetClass: "Stocks", referencePrice: 145.86, decimals: 2, spreadBps: 8, accent: "#8ce6a9" },
  { id: "tsla", symbol: "TSLA", name: "Tesla Inc.", exchange: "NASDAQ", assetClass: "Stocks", referencePrice: 247.60, decimals: 2, spreadBps: 12, accent: "#ef8f82" },
  { id: "msft", symbol: "MSFT", name: "Microsoft Corp.", exchange: "NASDAQ", assetClass: "Stocks", referencePrice: 426.34, decimals: 2, spreadBps: 5, accent: "#8bbaff" },
  { id: "spy", symbol: "SPY", name: "SPDR S&P 500 ETF", exchange: "NYSE ARCA", assetClass: "ETFs", referencePrice: 510.16, decimals: 2, spreadBps: 3, accent: "#8bbaff" },
  { id: "qqq", symbol: "QQQ", name: "Invesco QQQ Trust", exchange: "NASDAQ", assetClass: "ETFs", referencePrice: 444.21, decimals: 2, spreadBps: 4, accent: "#c3a4ff" },
  { id: "vfv", symbol: "VFV.TO", name: "Vanguard S&P 500 ETF", exchange: "TSX", assetClass: "ETFs", referencePrice: 146.79, decimals: 2, spreadBps: 8, accent: "#67c6b2" },
  { id: "aapl-opt", symbol: "AAPL 200C", name: "Example call option", exchange: "OPRA · illustrative", assetClass: "Options", referencePrice: 7.80, decimals: 2, spreadBps: 120, accent: "#eacb8e" },
  { id: "spy-opt", symbol: "SPY 500P", name: "Example put option", exchange: "OPRA · illustrative", assetClass: "Options", referencePrice: 5.15, decimals: 2, spreadBps: 150, accent: "#eacb8e" },
  { id: "es", symbol: "ESZ6", name: "E-mini S&P 500 Dec 2026", exchange: "CME · illustrative", assetClass: "Futures", referencePrice: 5834.75, decimals: 2, spreadBps: 2, accent: "#88b7f6" },
  { id: "nq", symbol: "NQZ6", name: "E-mini Nasdaq Dec 2026", exchange: "CME · illustrative", assetClass: "Futures", referencePrice: 20586.50, decimals: 2, spreadBps: 3, accent: "#d9a3f0" },
  { id: "eurusd", symbol: "EUR/USD", name: "Euro / US Dollar", exchange: "FX · indicative", assetClass: "Forex", referencePrice: 1.08460, decimals: 5, spreadBps: 2, accent: "#8fcba5" },
  { id: "gbpusd", symbol: "GBP/USD", name: "British Pound / US Dollar", exchange: "FX · indicative", assetClass: "Forex", referencePrice: 1.26510, decimals: 5, spreadBps: 3, accent: "#d5a2bc" },
  { id: "btcusd", symbol: "BTC/USD", name: "Bitcoin / US Dollar", exchange: "Crypto · illustrative", assetClass: "Crypto", referencePrice: 68275.50, decimals: 2, spreadBps: 20, accent: "#f5b969" },
  { id: "ethusd", symbol: "ETH/USD", name: "Ethereum / US Dollar", exchange: "Crypto · illustrative", assetClass: "Crypto", referencePrice: 3486.73, decimals: 2, spreadBps: 22, accent: "#a5adf2" },
];

const RANGES: Record<TimeRange, { bars: number; seconds: number }> = {
  "1D": { bars: 144, seconds: 600 },
  "1W": { bars: 168, seconds: 3600 },
  "1M": { bars: 180, seconds: 14400 },
  "3M": { bars: 180, seconds: 43200 },
  "1Y": { bars: 240, seconds: 86400 },
};

function seededRandom(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function stringSeed(value: string) {
  let hash = 2166136261;
  for (const character of value) {
    hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
  }
  return hash;
}

export function formatPrice(value: number, decimals = 2) {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatMoney(value: number) {
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function createDemoSeries(asset: Asset, range: TimeRange): MarketSeries {
  const { bars, seconds } = RANGES[range];
  const random = seededRandom(stringSeed(asset.id + range));
  // Use a fixed anchor so demo data never masquerades as a changing live feed.
  const lastTimestamp = Math.floor(Date.UTC(2026, 10, 13, 20, 0) / 1000 / seconds) * seconds;
  const volatility = asset.assetClass === "Crypto" ? 0.009 : asset.assetClass === "Options" ? 0.017 : 0.004;
  const unscaled: { open: number; high: number; low: number; close: number; time: UTCTimestamp; volume: number }[] = [];
  let close = asset.referencePrice * 0.96;

  for (let i = 0; i < bars; i++) {
    const open = close;
    const drift = (random() - 0.465) * volatility;
    close = Math.max(0.00001, open * (1 + drift));
    const high = Math.max(open, close) * (1 + random() * volatility * 0.65);
    const low = Math.min(open, close) * (1 - random() * volatility * 0.65);
    const time = (lastTimestamp - (bars - i - 1) * seconds) as UTCTimestamp;
    unscaled.push({ open, high, low, close, time, volume: 100_000 + Math.round(random() * 730_000) });
  }

  const scale = asset.referencePrice / unscaled[unscaled.length - 1].close;
  const precision = 10 ** asset.decimals;
  const round = (n: number) => Math.round(n * precision) / precision;
  const candles = unscaled.map((bar) => ({
    time: bar.time,
    open: round(bar.open * scale),
    high: round(bar.high * scale),
    low: round(bar.low * scale),
    close: round(bar.close * scale),
  }));
  const volumes = unscaled.map((bar, index) => ({
    time: bar.time,
    value: bar.volume,
    color: candles[index].close >= candles[index].open ? "rgba(53, 202, 152, .32)" : "rgba(249, 104, 111, .27)",
  }));
  const first = candles[0].open;
  const last = candles[candles.length - 1].close;
  return {
    candles,
    volumes,
    change: last - first,
    changePct: ((last - first) / first) * 100,
    high: Math.max(...candles.map((bar) => bar.high)),
    low: Math.min(...candles.map((bar) => bar.low)),
  };
}
