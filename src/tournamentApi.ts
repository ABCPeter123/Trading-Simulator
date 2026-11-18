import {request} from "./api";
import type {PortfolioSeason} from "./portfolioApi";

export interface TournamentVersion {
  id:string;name:string;mode:"portfolio_model";version:1|2;source_job_id:string;source_rank:number;
  symbols:string[];model:string;max_position_pct:number;delay_sessions:1|2;
  research_only?:boolean;
  rebalance_sessions:number;restricted_research:boolean;short_proxy_research:boolean;
  code:string;created_at:string;
}

export const modelDescription=(model:string):string=>({
  equal_weight:"Allocate equal starting weights, then enforce per-asset and asset-class risk caps.",
  inverse_volatility:"Allocate more to assets with lower trailing 60-session volatility, subject to risk caps.",
  trend_filter:"Hold assets above their 126-session average and size them by inverse volatility.",
  relative_momentum:"Select the strongest positive blend of 64- and 127-session momentum, sized by inverse volatility.",
  volatility_target:"Use inverse-volatility weights and reduce total exposure toward a 12% annual risk target.",
  defensive_rotation:"Allocate across growth assets when their trends are healthy, then rotate toward actual bonds and commodities during weaker equity trends.",
  diversified_risk_parity:"Build inverse-volatility long positions across equities and defensive asset classes with tighter class-level concentration limits.",
  equity_hedge:"Combine equity exposure with actual bond and commodity holdings to reduce dependence on one asset class.",
  leveraged_trend:"Research-only: borrow cash to target up to 135% gross long equity exposure in positive-trend stocks, with financing cost and maintenance-risk modeling.",
  long_short_momentum:"Research-only: hold positive exposure to the strongest equity momentum assets and short the weakest, including borrow fees.",
  market_neutral:"Research-only: target approximately balanced long and short equity exposures based on momentum, subject to position and financing limits.",
} as Record<string,string>)[model]??"Unsupported allocation model.";

export const importTournamentRank=(jobId:string,rank:number)=>
  request<TournamentVersion>(
    "/live/research/universe/jobs/"+encodeURIComponent(jobId)+
    "/strategies/"+encodeURIComponent(String(rank)),{method:"POST"});

export const listTournamentVersions=()=>request<TournamentVersion[]>(
  "/live/research/universe/strategies");

export const createTournamentReplay=(strategyId:string)=>
  request<PortfolioSeason>("/portfolio-seasons/from-tournament",{
    method:"POST",body:JSON.stringify({strategy_id:strategyId,period:"MAX",starting_point:0.3}),
  });

export interface TournamentSourceSpec {
  version:1|2; model:string; symbols:string[]; max_position_pct:number;
  delay_sessions:1|2; rebalance_sessions:number;
  restricted_research?:boolean; short_proxy_research?:boolean; research_only?:boolean;
  target_investment_pct?:number;equity_class_cap_pct?:number;redistribute_excess?:boolean;
}

export interface PythonStrategySection {
  label:string; function:string; path:string; first_line:number; sha256:string; code:string;
}

export interface PythonStrategyFile {
  path:string; sha256:string; code:string;
}

export interface PythonStrategySource {
  runtime:string; model:string; context:"research"|"simulation"|"live";
  entry_point:string; research_execution_entry_point:string;
  sections:PythonStrategySection[]; files:PythonStrategyFile[];
  research_only:boolean; executable:boolean;
}

/** These sources come directly from the running local Python backend, not from a UI model. */
export const getTournamentPythonSource = (
  spec:TournamentSourceSpec,context:"research"|"simulation"|"live"="research",
) => request<PythonStrategySource>("/live/research/universe/strategy-source",{
  method:"POST",body:JSON.stringify({spec,context}),
});

export interface CustomPeriodRequest {
  spec:TournamentSourceSpec;
  start_date?:string|null;
  end_date?:string|null;
  max_position_pct?:number;
  delay_sessions?:1|2;
  slippage_bps?:number;
  target_investment_pct?:number;
  equity_class_cap_pct?:number;
  redistribute_excess?:boolean;
}
export interface CustomPeriodMetric {
  return_pct:number; max_drawdown_pct:number; annualized_volatility_pct:number|null;
  sharpe:number|null;sortino:number|null; trades:number; fees:number;
  turnover_pct:number;average_invested_pct:number;
  average_gross_exposure_pct?:number;peak_gross_leverage?:number;
  margin_interest?:number;short_borrow_cost?:number;margin_calls?:number;
}
export interface CustomPeriodResult {
  requested_window:{start_date:string|null;end_date:string|null};
  actual_window:{start_date:string;end_date:string;sessions:number;
    warmup_sessions:number;available_start:string;available_end:string};
  model:string;research_only:boolean;
  assumptions:Record<string,string|number|boolean>;
  metrics:CustomPeriodMetric;benchmark:CustomPeriodMetric;execution_stress:CustomPeriodMetric;
  periods:{
    monthly:{month:string;ending_equity:number;return_pct:number;pnl_usd:number;observed_sessions:number}[];
    best_month:{month:string;return_pct:number;pnl_usd:number};
    worst_month:{month:string;return_pct:number;pnl_usd:number};
    monthly_average_pct:number; positive_months:number;observed_months:number;
    worst_day:{return_pct:number;start:string;end:string}|null;
    worst_five_sessions:{return_pct:number;start:string;end:string}|null;
    worst_21_sessions:{return_pct:number;start:string;end:string}|null;
    worst_drawdown:{drawdown_pct:number;peak_date:string|null;trough_date:string|null};
  };
  equity_curve:{time:number;value:number}[];
  benchmark_curve:{time:number;value:number}[];
  fills:{time:number;symbol:string;side:string;quantity:number;price:number;fee:number;notional:number}[];
  fills_total:number;
  limitations:string[];
}
export interface CustomPeriodJob {
  id:string;status:"queued"|"running"|"completed"|"failed"|"cancelled";
  created_at:string;updated_at:string;progress:number;stage:string;
  error_code:string|null;result:CustomPeriodResult|null;
}
export const createCustomPeriodStudy=(body:CustomPeriodRequest)=>
  request<CustomPeriodJob>("/live/research/strategy-period/jobs",{
    method:"POST",body:JSON.stringify(body),
  });
export const getCustomPeriodStudy=(id:string)=>
  request<CustomPeriodJob>("/live/research/strategy-period/jobs/"+encodeURIComponent(id));
export const cancelCustomPeriodStudy=(id:string)=>
  request<CustomPeriodJob>("/live/research/strategy-period/jobs/"+encodeURIComponent(id)+"/cancel",{
    method:"POST",
  });
