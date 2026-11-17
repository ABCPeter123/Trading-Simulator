import { apiUrl, cloudFrontend, privateRequestHeaders } from "./privateConnection";
import type { ReplayResolution, ReplayWindow } from "./replayIntervals";
import type { AssetClass, TimeRange, TradeSide } from "./types";

export interface MarketBar { time: number; open: number; high: number; low: number; close: number; volume: number }
export interface HistoryResponse {
  asset_id: string; range: string; source: string; currency: string;
  bars: MarketBar[]; as_of: string; is_demo: boolean; delayed_or_indicative: boolean;
}
export interface QuoteResponse {
  asset_id: string; price: number; bid: number | null; ask: number | null;
  currency: string; timestamp: string; source: string; as_of_age_seconds: number;
  market_open: boolean; fresh: boolean; tradable: boolean; spread_bps: number;
  execution_model: string; block_reason: string | null;
}
export interface Fill {
  id: string; asset_id: string; side: TradeSide; quantity: number;
  price: number; fee: number; created_at: string; source: string; quote_time: string;
}
export interface Position {
  asset_id: string; quantity: number; average_cost: number; mark: number | null;
  market_value: number | null; unrealized_pnl: number | null;
}
export interface AccountResponse {
  cash: number; equity: number | null; realized_pnl: number;
  unrealized_pnl: number | null; positions: Position[]; fills: Fill[];
  has_unpriced_positions: boolean;
}
export interface BacktestResponse {
  asset_id: string; strategy: string; fast: number; slow: number;
  starting_cash: number; ending_equity: number; return_pct: number;
  buy_hold_pct: number; max_drawdown_pct: number;
  trades: {time: number; side: TradeSide; quantity: number; fill: number; fee: number}[];
  equity_curve: {time: number; value: number}[];
  execution: string; data_source: string;
}

export async function request<T>(route: string, options?: RequestInit): Promise<T> {
  const response = await fetch(apiUrl(`/api${route}`), {
    ...options,
    headers: privateRequestHeaders({ "Content-Type": "application/json", ...options?.headers }),
    cache: cloudFrontend ? "no-store" : options?.cache,
  });
  let payload: unknown;
  try { payload = await response.json(); }
  catch { throw new Error(cloudFrontend ? "Private engine connection failed. Check your tunnel and access token." : "Local API is unreachable. Start the Python backend on port 8000."); }
  if (!response.ok) {
    const detail = typeof payload === "object" && payload !== null && "detail" in payload ? payload.detail : null;
    throw new Error(typeof detail === "string" ? detail : `Request failed (${response.status})`);
  }
  return payload as T;
}
export function getHistory(assetId: string, range: TimeRange | ReplayWindow, resolution?: ReplayResolution) {
  return request<HistoryResponse>(`/market/${assetId}?range=${range}${resolution ? `&resolution=${resolution}` : ""}`);
}
export function getQuote(assetId: string) {
  return request<QuoteResponse>(`/quotes/${assetId}`);
}
export function getAccount() {
  return request<AccountResponse>("/account");
}
export function sendOrder(assetId: string, side: TradeSide, quantity: string) {
  return request<{fill: Fill; account: AccountResponse}>("/orders", {
    method: "POST", body: JSON.stringify({asset_id: assetId, side, quantity}),
  });
}
export function resetAccount() {
  return request<AccountResponse>("/account/reset", {method: "POST"});
}
export function getBacktest(assetId: string, fast: number, slow: number) {
  return request<BacktestResponse>(`/backtest/${assetId}?fast=${fast}&slow=${slow}`);
}
export function supportsCashTrading(assetId: string, assetClass: AssetClass) {
  return !["Options", "Futures"].includes(assetClass) && assetId !== "vfv";
}

export interface MarketCoverage {
  asset_id:string;window:string;resolution:string;provider:string;currency:string;
  bars:number;status:string;first_bar:number|null;last_bar:number|null;
  age_seconds:number|null;coverage_pct:number|null;
  gaps:{after:number;before:number;missing_estimate:number}[];
  duplicate_timestamps:number;note?:string;
}
export interface MarketSubscription {
  asset_id:string;resolution:string;active:number;last_attempt:string|null;
  last_success:string|null;last_bar:number|null;records:number;failure_code:string|null;
}
export const getMarketCoverage=(assetId:string,window:string,resolution:string)=>
  request<MarketCoverage>("/market-data/coverage/"+encodeURIComponent(assetId)+
    "?window="+encodeURIComponent(window)+"&resolution="+encodeURIComponent(resolution));
export const getMarketSubscriptions=()=>request<MarketSubscription[]>("/market-data/subscriptions");
export const subscribeMarket=(assetId:string,resolution:string)=>
  request<{asset_id:string;resolution:string;active:boolean}>("/market-data/subscriptions",{
    method:"POST",body:JSON.stringify({asset_id:assetId,resolution}),
  });
export const unsubscribeMarket=(assetId:string,resolution:string)=>
  request<{asset_id:string;resolution:string;active:boolean}>("/market-data/subscriptions/"+
    encodeURIComponent(assetId)+"/"+encodeURIComponent(resolution),{method:"DELETE"});

export const getArchivedMarketHistory=(assetId:string,window:string,resolution:string)=>
  request<HistoryResponse>("/market-data/archived/"+encodeURIComponent(assetId)+
    "?window="+encodeURIComponent(window)+"&resolution="+encodeURIComponent(resolution));
