import type { CandlestickData, HistogramData, UTCTimestamp } from "lightweight-charts";

export type AssetClass = "Stocks" | "ETFs" | "Options" | "Futures" | "Forex" | "Crypto";
export type TimeRange = "1D" | "1W" | "1M" | "3M" | "1Y";
export type ChartStyle = "candles" | "line";
export type TradeSide = "buy" | "sell";

export interface Asset {
  id: string;
  symbol: string;
  name: string;
  exchange: string;
  assetClass: AssetClass;
  referencePrice: number;
  decimals: number;
  spreadBps: number;
  accent: string;
}

export interface MarketSeries {
  candles: CandlestickData<UTCTimestamp>[];
  volumes: HistogramData<UTCTimestamp>[];
  change: number;
  changePct: number;
  high: number;
  low: number;
}

export interface DemoTrade {
  id: string;
  assetId: string;
  side: TradeSide;
  quantity: number;
  price: number;
  createdAt: string;
}

export interface DemoAccount {
  cash: number;
  trades: DemoTrade[];
}
