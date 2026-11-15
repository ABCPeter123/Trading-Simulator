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

export const gameRuns = () => request<SavedArcadeRun[]>("/arcade/runs");
export const gameLoad = (id: string) => request<ArcadeRun>(`/arcade/${encodeURIComponent(id)}`);
export const gameStart = (assetId: string, startingPoint: number) =>
  request<ArcadeRun>("/arcade/new", {method: "POST", body: JSON.stringify({asset_id: assetId, starting_point: startingPoint})});
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
