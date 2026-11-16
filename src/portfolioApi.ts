import type { ReplayResolution, ReplayWindow } from "./replayIntervals";
import { request } from "./api";
import type { MarketBar } from "./api";
import type { TradeSide } from "./types";

export interface PortfolioPosition {
  asset_id: string;
  quantity: number;
  average_cost: number;
  last_price: number | null;
  mark_day: string | null;
  market_value: number;
  unrealized_pnl: number | null;
  realized_pnl: number;
  has_bar_today: boolean;
}
export interface PortfolioOrder {
  id: string;
  asset_id: string;
  side: TradeSide;
  kind: "market" | "limit" | "stop";
  size: string;
  size_type: "percent" | "units";
  price: string | null;
  source: "bot" | "manual";
  placed_step: number;
}
export interface PortfolioFill {
  order_id: string;
  asset_id: string;
  side: TradeSide;
  kind: string;
  source: string;
  quantity: number;
  price: number;
  fee: number;
  time: number;
}
export interface PortfolioSeason {
  id: string;
  asset_ids: string[];
  period: ReplayWindow;
  resolution: ReplayResolution;
  sources: Record<string, string>;
  day: string;
  current_step: number;
  history_start: number;
  live_index: number;
  view_index: number;
  viewing_past: boolean;
  checkpoint_count: number;
  total_steps: number;
  progress_pct: number;
  finished: boolean;
  bars: Record<string, MarketBar[]>;
  metrics: {
    cash: number; exposure: number; equity: number; return_pct: number;
    equal_weight_hold_pct: number; max_drawdown_pct: number;
    xp: number; level: number; score: number; badges: string[];
  };
  positions: PortfolioPosition[];
  orders: PortfolioOrder[];
  fills: PortfolioFill[];
  events: string[];
  strategy: string;
  risk: {stop_loss_pct: number; take_profit_pct: number};
  curve: {day: string; value: number}[];
  execution_notice: string;
}
export interface PortfolioSaved {
  id: string; asset_ids: string[]; period: string; updated_at: string;
}
const base = "/portfolio-seasons";
export const listPortfolioSeasons = () => request<PortfolioSaved[]>(base);
export const newPortfolioSeason = (assetIds: string[], period: ReplayWindow, startDate?: string, resolution: ReplayResolution = "1d") =>
  request<PortfolioSeason>(base, {method:"POST", body: JSON.stringify({
    asset_ids: assetIds, period, resolution, start_date: startDate || null,
  })});
export const loadPortfolioSeason = (id: string) =>
  request<PortfolioSeason>(`${base}/${encodeURIComponent(id)}`);
export const advancePortfolio = (id: string, count: number, untilAction = false) =>
  request<PortfolioSeason>(`${base}/${id}/advance`, {
    method:"POST", body:JSON.stringify({count, until_action: untilAction}),
  });
export const tradePortfolio = (id: string, settings: {
  asset_id: string; side: TradeSide; kind: "market" | "limit" | "stop";
  size: string; size_type: "percent" | "units"; price?: string;
}) => request<PortfolioSeason>(`${base}/${id}/orders`, {
  method:"POST", body:JSON.stringify(settings),
});
export const cancelPortfolioOrder = (id: string, orderId: string) =>
  request<PortfolioSeason>(`${base}/${id}/orders/${encodeURIComponent(orderId)}`, {method:"DELETE"});
export const savePortfolioStrategy = (id: string, code: string) =>
  request<PortfolioSeason>(`${base}/${id}/strategy`, {method:"PUT", body:JSON.stringify({code})});
export const savePortfolioRisk = (id: string, stop: number, target: number) =>
  request<PortfolioSeason>(`${base}/${id}/risk`, {method:"PUT", body:JSON.stringify({
    stop_loss_pct:stop, take_profit_pct:target,
  })});

export const portfolioAt = (id: string, step: number) =>
  request<PortfolioSeason>(`/portfolio-seasons/${encodeURIComponent(id)}/at/${step}`);
