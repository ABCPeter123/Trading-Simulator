export type AssetClass = "Stocks" | "ETFs" | "Options" | "Futures" | "Forex" | "Crypto" | "Indices" | "Funds";
export type TimeRange = "1D" | "1W" | "1M" | "3M" | "1Y";
export type ChartStyle = "candles" | "line";
export type TradeSide = "buy" | "sell";

export interface Asset {
  id: string;
  symbol: string;
  name: string;
  exchange: string;
  assetClass: AssetClass;
  decimals: number;
  spreadBps: number;
  accent: string;
}

