import { request } from "./api";

export interface AnalyticsPoint {
  day: string;
  equity: number;
  benchmark: number;
  cash: number;
  invested: number;
  return_pct: number;
  benchmark_pct: number;
  fee_total: number;
  drawdown_pct: number;
}
export interface RollingResult {
  return_pct: number;
  benchmark_pct: number;
  start_day: string;
  end_day: string;
}
export interface Attribution {
  asset_id: string;
  quantity: number;
  average_cost: number;
  last_close: number;
  invested: number;
  weight_pct: number;
  realized_pnl: number;
  unrealized_pnl: number;
  price_return_pct: number | null;
  last_observed_day: string;
}
export interface StrategyExecution {
  day: string;
  time: number;
  asset_id: string;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  fee: number;
  notional: number;
  source: string;
  cash_change: number;
}
export interface StrategyReport {
  start_day: string;
  end_day: string;
  sessions: number;
  curve: AnalyticsPoint[];
  summary: {
    total_return_pct: number;
    benchmark_return_pct: number;
    excess_return_pct: number;
    max_drawdown_pct: number;
    current_equity: number;
    current_cash: number;
    current_invested: number;
    total_fees: number;
    total_notional_traded: number;
    fill_count: number;
    winning_exits: number;
    losing_exits: number;
    profitable_exit_rate_pct: number | null;
    step_sharpe: number | null;
  };
  rolling: Record<string, RollingResult | null>;
  allocations: Attribution[];
  executions: StrategyExecution[];
  methodology: string;
}

export const getStrategyReport = (mode: "portfolio" | "single", id: string) =>
  request<StrategyReport>(
    mode === "portfolio"
      ? `/portfolio-seasons/${encodeURIComponent(id)}/analytics`
      : `/arcade/${encodeURIComponent(id)}/analytics`,
  );
