import type { MarketBar } from "./api";
import { request } from "./api";
import type { TradeSide } from "./types";

export type OrderKind = "market" | "limit" | "stop";
export interface ArcadeOrder {
  id: string;
  side: TradeSide;
  kind: OrderKind;
  size: string;
  size_type: "percent" | "units";
  price: string | null;
  source: "manual" | "bot";
  placed_bar: number;
}
export interface ArcadeFill {
  order_id: string;
  side: TradeSide;
  quantity: number;
  price: number;
  fee: number;
  source: "manual" | "bot";
  kind: OrderKind;
  time: number;
}
export interface ArcadeMetrics {
  cash: number;
  quantity: number;
  average_cost: number;
  equity: number;
  position_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  return_pct: number;
  buy_hold_pct: number;
  max_drawdown_pct: number;
  score: number;
  xp: number;
  level: number;
  badges: string[];
}
export interface ArcadeRun {
  id: string;
  asset_id: string;
  source: string;
  period: string;
  risk: {stop_loss_pct: number; take_profit_pct: number};
  current_bar: number;
  total_bars: number;
  finished: boolean;
  progress_pct: number;
  bars: MarketBar[];
  orders: ArcadeOrder[];
  fills: ArcadeFill[];
  events: string[];
  strategy: string;
  equity_curve: {time: number; value: number}[];
  metrics: ArcadeMetrics;
  examples: {title: string; code: string}[];
  updated_at: string;
  execution_notice: string;
}
export interface SavedArcadeRun {
  id: string;
  asset_id: string;
  updated_at: string;
}

export interface CatalogInstrument {
  id: string;
  symbol: string;
  name: string;
  asset_class: string;
  currency: string;
  tradable: boolean;
  decimals: number;
}
export const gameCatalog = () => request<CatalogInstrument[]>("/instruments?limit=250");
export const gameSetRisk = (id: string, stopLossPct: number, takeProfitPct: number) =>
  request<ArcadeRun>(`/arcade/${id}/risk`, {
    method: "PUT", body: JSON.stringify({stop_loss_pct: stopLossPct, take_profit_pct: takeProfitPct}),
  });
export const gameRuns = () => request<SavedArcadeRun[]>("/arcade/runs");
export const gameLoad = (id: string) => request<ArcadeRun>(`/arcade/${encodeURIComponent(id)}`);
export const gameStart = (assetId: string, startingPoint: number, period: "1Y"|"2Y"|"5Y"|"10Y"|"MAX", startDate?: string) =>
  request<ArcadeRun>("/arcade/new", {method: "POST", body: JSON.stringify({asset_id: assetId, starting_point: startingPoint, period, start_date: startDate || null})});
export const gameStep = (id: string, count: number, untilAction = false) =>
  request<ArcadeRun>(`/arcade/${id}/advance`, {method: "POST", body: JSON.stringify({count, until_action: untilAction})});
export const gameTrade = (id: string, order: {side: TradeSide; kind: OrderKind; size: string; size_type: "percent" | "units"; price?: string}) =>
  request<ArcadeRun>(`/arcade/${id}/orders`, {method: "POST", body: JSON.stringify(order)});
export const gameCancel = (id: string, orderId: string) =>
  request<ArcadeRun>(`/arcade/${id}/orders/${orderId}`, {method: "DELETE"});
export const gameSaveCode = (id: string, code: string) =>
  request<ArcadeRun>(`/arcade/${id}/strategy`, {method: "PUT", body: JSON.stringify({code})});
export const gameValidateCode = (code: string) =>
  request<{valid: boolean; rules: {line: number; left: string; operator: string; right: string; side: string; percent: number}[]}>(
    "/arcade/validate", {method: "POST", body: JSON.stringify({code})},
  );

export interface DiscoveredInstrument {
  symbol: string; name: string; asset_class: string; exchange: string; currency: string;
}
export const gameDiscover = (query: string) =>
  request<DiscoveredInstrument[]>(`/instruments/discover?search=${encodeURIComponent(query)}`);
export const gameImportTicker = (symbol: string) =>
  request<CatalogInstrument>("/instruments/import", {
    method:"POST", body:JSON.stringify({symbol}),
  });
