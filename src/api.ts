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

/** Extracts a safe, actionable message from FastAPI/Pydantic validation errors. */
export function apiErrorMessage(status: number, payload: unknown): string {
  const fallback = status === 422
    ? "Request rejected (422). Check the submitted values and try again."
    : `Request failed (${status})`;
  if (!payload || typeof payload !== "object" || !("detail" in payload)) return fallback;
  const detail = payload.detail;
  if (typeof detail === "string") return detail.trim().slice(0, 500) || fallback;
  if (!Array.isArray(detail)) return fallback;
  const messages: string[] = [];
  for (const issue of detail.slice(0, 3)) {
    if (!issue || typeof issue !== "object") continue;
    const location = "loc" in issue && Array.isArray(issue.loc) ? issue.loc : [];
    const field = location.filter((item): item is string =>
      typeof item === "string" && item !== "body" && item !== "query" &&
      /^[A-Za-z_][A-Za-z0-9_]*$/.test(item)).slice(0, 2).join(".");
    const message = "msg" in issue && typeof issue.msg === "string"
      ? issue.msg.trim().slice(0, 160) : "";
    if (message) messages.push((field ? field.replaceAll("_", " ") + ": " : "") + message);
  }
  return messages.length ? `Invalid request (${status}): ${messages.join("; ")}` : fallback;
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
    throw new Error(apiErrorMessage(response.status, payload));
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
export interface MarketCollectorHealth {
  collector: {state:"polling"|"idle"|"stale"|"unverified";
    last_heartbeat:string|null;heartbeat_age_seconds:number|null;last_attempted:number};
  active:number;subscriptions:number;errors:number;delivery_guaranteed:boolean;
  reconciliation_jobs:number;
  last_updates:{asset_id:string;resolution:string;active:boolean;sync_state:string;
    failure_code:string|null;last_success:string|null;last_bar:number|null;
    bootstrap:MarketReconciliationJob|null;
    reconciliation:MarketReconciliationJob|null}[];
}
export interface MarketReconciliationJob {
  asset_id:string;resolution:string;kind:"bootstrap"|"reconcile";
  due_at:string;last_attempt:string|null;last_success:string|null;
  failures:number;error_code:string|null;verified_bars:number;
  verified_through:number|null;status:"pending"|"retry_pending"|"provider_checked";
}
export const getMarketCollectorHealth=()=>request<MarketCollectorHealth>("/market-data/health");
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
