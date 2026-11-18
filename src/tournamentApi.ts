import {request} from "./api";
import type {PortfolioSeason} from "./portfolioApi";

export interface TournamentVersion {
  id:string;name:string;mode:"portfolio_model";version:1|2;source_job_id:string;source_rank:number;
  symbols:string[];model:string;max_position_pct:number;delay_sessions:1|2;
  sleeves?:{model:string;weight_pct:number}[]|null;
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
  sleeves?:{model:string;weight_pct:number}[]|null;
  base_currency?:"USD"|"CAD";slippage_bps?:number;commission_usd?:number;fx_conversion_bps?:number;
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

export interface WalkForwardRequest {
  spec:TournamentSourceSpec;
  search_width:"focused"|"extended"|"comprehensive";
  target_cagr_pct:number;
  target_sharpe:number;
  risk_free_pct:number;
  max_drawdown_pct:number;
  minimum_training_cagr_pct?:number;
  minimum_excess_cagr_pct_points?:number;
  min_average_invested_pct?:number;
  slippage_bps:number;
  base_currency?:"USD"|"CAD";commission_usd?:number;fx_conversion_bps?:number;
}
export interface WalkForwardQuality {
  cagr_pct:number|null;excess_sharpe:number|null;
  annualized_volatility_pct:number|null;sessions:number;
}
export interface WalkForwardSelection {
  model:string;max_position_pct:number;delay_sessions:1|2;
  sleeves?:{model:string;weight_pct:number}[];
  target_investment_pct?:number;equity_class_cap_pct?:number;
  redistribute_excess?:boolean;
}
export interface WalkForwardBenchmark {
  id:"same_basket_equal_weight"|"constant_cash_hurdle";
  name:string;return_pct:number;cagr_pct:number|null;excess_sharpe:number|null;
  drawdown_pct:number;volatility_pct:number|null;
  excess_return_vs_selected_pct_points:number;
}
export interface WalkForwardBenchmarkComparison {
  benchmarks:WalkForwardBenchmark[];selected_return_pct:number;
  reproducible_comparison:boolean;limitations:string[];
}
export interface WalkForwardExposure {
  starting_capital_usd:number;ending_equity_usd:number|null;
  average_gross_invested_pct:number|null;average_net_exposure_pct:number|null;
  average_rebalance_cash_pct:number|null;final_cash_pct:number|null;
  average_category_gross_pct:Record<string,number>;
  average_largest_position_share_of_gross_pct:number|null;
  position_snapshots:number;snapshot_definition:string;
  turnover_pct_of_initial_capital:number|null;
  explicit_fees_and_financing_usd:number|null;
  transaction_fees_usd:number|null;margin_interest_usd:number|null;
  short_borrow_cost_usd:number|null;trade_count:number;
  turnover_interpretation:string;
}
export interface WalkForwardCandidates {
  eligible_count:number;attempted_count:number;rejected_count:number;
  rejection_reasons:Record<string,number>;
  best_by_training_score:{
    rank:number;config:WalkForwardSelection;training_score:number;
    training_cagr_pct:number|null;training_excess_sharpe:number|null;
    training_drawdown_pct:number;training_turnover_pct:number|null;
    training_average_invested_pct:number;score_components:Record<string,number>;
  }[];
  basis:string;
}
export interface WalkForwardStability {
  cap_perturbation_pct_points:number;pre_audit_only:boolean;
  variants:{max_position_pct:number;selected_setting:boolean;cagr_pct?:number|null;
    excess_sharpe?:number|null;drawdown_pct?:number;turnover_pct?:number|null;
    error?:string}[];
  cagr_range_pct_points:number|null;interpretation:string;
}
export interface MarketBenchmark {
  status:"available"|"unavailable";symbol:"SPY";reason?:string;
  method?:string;source?:string;first_session?:string;last_session?:string;
  matched_sessions?:number;return_pct?:number;cagr_pct?:number|null;
  excess_sharpe?:number|null;drawdown_pct?:number;
  commission_usd?:number;fx_bps_on_buy?:number;
  spread_bps?:number;slippage_bps_on_buy?:number;
  income_treatment?:string;selection_used_this_reference?:false;
}
export interface ResearchReview {
  status:"diagnostic_only"|"unavailable";reason?:string;model?:string;
  findings?:{code:string;severity:"high"|"medium"|"info";basis:string;
    observation:string;evidence:Record<string,number>}[];
  next_experiments?:{id:string;priority:number;title:string;method:string;
    evidence_basis:string;automatic_execution:false}[];
  summary?:{audit_cagr_pct:number|null;audit_excess_sharpe:number|null;
    assumed_cash_rate_pct:number;critical_findings:number;
    training_candidates_eligible?:number;training_candidates_attempted?:number};
  integrity?:{audit_already_opened:true;selection_changed:false;
    experiments_queued:0;read_only:true;broker_orders:0;warning:string};
}
export interface OriginalTournamentReference {
  status:"available"|"unavailable";
  interpretation:string;reason?:string;
  selected_by_walkforward:false;selection_input:false;research_only:true;
  configuration:WalkForwardSelection;
  training_gate?:string;training_score?:number;
  training_drawdown_pct?:number;training_cagr_pct?:number|null;
  training_excess_sharpe?:number|null;training_average_invested_pct?:number;
  return_pct?:number;cagr_pct?:number|null;excess_sharpe?:number|null;
  drawdown_pct?:number;average_invested_pct?:number;
  turnover_pct?:number;trades?:number;
}
export interface WalkForwardFold {
  fold:number;training_end:string;out_of_sample_start:string;out_of_sample_end:string;
  training_sessions:number;out_of_sample_sessions:number;trials_evaluated:number;
  eligible_trials:number;selected:WalkForwardSelection;selection_score:number;
  training_objectives:WalkForwardQuality;out_of_sample_objectives:WalkForwardQuality;
  out_of_sample_return_pct:number;out_of_sample_drawdown_pct:number;
  trades:number;fees:number;
  selection_score_breakdown?:{total:number;components:Record<string,number>};
  training_candidate_diagnostics?:WalkForwardCandidates;
  unseen_benchmark_comparison?:WalkForwardBenchmarkComparison;
  original_tournament_reference?:OriginalTournamentReference;
  unseen_spy_price_benchmark?:MarketBenchmark;
  unseen_exposure_and_costs?:WalkForwardExposure;
}
export interface WalkForwardConsistency {
  rolling_window_sessions:number;rolling_windows:number;
  worst_rolling_12m_pct:number|null;best_rolling_12m_pct:number|null;
  positive_rolling_window_pct:number|null;
  target_hit_rolling_window_pct:number|null;
  calendar_years:{year:number;sessions:number;complete:boolean;return_pct:number}[];
  complete_calendar_years:number;worst_complete_calendar_year_pct:number|null;
  all_complete_years_positive:boolean|null;interpretation:string;
}
export interface RiskFrontier {
  basis:string;risk_limits_pct:number[];
  observation_boundary:string;cannot_reselect_final_audit:true;
  not_an_independent_test_after_inspection:true;
  experiments:{
    max_training_drawdown_pct:number;is_configured_limit:boolean;
    folds_with_eligible_candidate:number;fold_count:number;
    pre_audit_final_training_eligible_count:number;
    pre_audit_final_training_has_candidate:boolean;
    status:"full_pre_audit_folds"|"incomplete_pre_audit_folds";
    validation_cagr_pct?:number|null;validation_excess_sharpe?:number|null;
    validation_drawdown_pct?:number;
    no_final_audit_replay:true;not_used_for_selection:true;
    folds:{fold:number;eligible_training_candidates:number;
      status:"qualified"|"no_eligible_candidate";
      selected?:WalkForwardSelection;out_of_sample_return_pct?:number;
      out_of_sample_cagr_pct?:number|null;out_of_sample_drawdown_pct?:number}[];
  }[];
}
export interface RejectionDiagnostics {
  attempted_count:number;eligible_count:number;rejected_count:number;
  rejection_reasons:Record<string,number>;
  thresholds:{max_training_drawdown_pct:number;
    minimum_training_cagr_pct:number;minimum_excess_cagr_pct_points:number;
    min_average_invested_pct:number};
}
export interface WalkForwardResult {
  status:"completed"|"insufficient_history"|"no_eligible_candidate";
  research_only:boolean;no_real_orders:boolean;
  sessions_available?:number;minimum_requirements?:string;
  reason?:string;fold_failed?:number|string;
  selection_outcome?:string;rejection_diagnostics?:RejectionDiagnostics;
  coverage?:{first_date:string;last_date:string;shared_sessions:number;warmup_sessions:number};
  targets?:{cagr_pct:number;excess_sharpe:number;max_drawdown_pct:number;risk_free_pct:number};
  execution_assumptions?:{base_currency:string;commission_usd:number;fx_conversion_bps:number;slippage_bps:number};
  research_review?:ResearchReview;
  eligibility_policy?:{
    minimum_training_cagr_pct:number;minimum_excess_cagr_pct_points:number;
    min_average_invested_pct:number;growth_target_is_a_hard_gate:false;reason:string
  };
  model_search?:{width:string;candidate_count:number;total_train_evaluations:number;
    candidate_scope:string;
    pre_audit_candidate_leaderboard?:WalkForwardCandidates;
    pre_audit_parameter_stability?:WalkForwardStability;
    pre_audit_risk_frontier?:RiskFrontier;
    pre_audit_selection_diagnostics?:{
      basis:string;valid_candidate_curves:number;attempted_candidates:number;
      deflated_sharpe:{status:string;probability_pct:number|null;
        expected_max_sharpe:number|null;annualized_selected_sharpe:number|null;
        sessions:number;assumed_trials:number;valid_competitors?:number;method?:string};
      pbo:{status:string;estimated_pbo_pct:number|null;
        negative_logit_splits:number;evaluated_splits:number;
        distinct_candidates:number;blocks:number;median_oos_rank_logit?:number;method?:string};
    };
  };
  walk_forward?:{
    folds:WalkForwardFold[];positive_folds:number;fold_count:number;
    stitch_method:string;aggregate_objectives:WalkForwardQuality;aggregate_drawdown_pct:number;
    consistency?:WalkForwardConsistency;
    curve:{time:number;value:number}[];
    multiplicity_approximation:{raw_approx_p:number|null;bonferroni_approx_p:number|null;assumed_trials:number};
  };
  final_audit?:{
    selected:WalkForwardSelection;selection_score:number;trials_evaluated:number;eligible_trials:number;
    selection_score_breakdown?:{total:number;components:Record<string,number>};
    benchmark_comparison?:WalkForwardBenchmarkComparison;
    original_tournament_reference?:OriginalTournamentReference;
    market_benchmark?:MarketBenchmark;
    exposure_and_costs?:WalkForwardExposure;
    start_date:string;end_date:string;sessions:number;objectives:WalkForwardQuality;
    consistency?:WalkForwardConsistency;
    prior_selected_comparison?:{
      objective:"highest_growth"|"highest_sharpe"|"balanced";
      selected:WalkForwardSelection;training_objectives:WalkForwardQuality;
      audit_objectives:WalkForwardQuality;audit_return_pct:number;
      audit_drawdown_pct:number;audit_trades:number;
    }[];
    return_pct:number;drawdown_pct:number;stress_objectives:WalkForwardQuality;
    stress_return_pct:number;severe_stress_return_pct?:number;
    execution_stress_scenarios?:{name:string;delay_sessions:number;slippage_bps:number;return_pct:number}[];
    observed_targets_met:boolean;trades:number;fees:number;
    curve:{time:number;value:number}[];
  };
  limitations?:string[];
}
export interface WalkForwardJob {
  id:string;status:"queued"|"running"|"completed"|"failed"|"cancelled";
  created_at:string;updated_at:string;progress:number;stage:string;
  error_code:string|null;result:WalkForwardResult|null;
}
export const submitWalkForward=(body:WalkForwardRequest)=>
  request<WalkForwardJob>("/live/research/walkforward/jobs",{
    method:"POST",body:JSON.stringify(body),
  });
export const getWalkForward=(id:string)=>
  request<WalkForwardJob>("/live/research/walkforward/jobs/"+encodeURIComponent(id));
export const listWalkForward=()=>
  request<WalkForwardJob[]>("/live/research/walkforward/jobs");
export const cancelWalkForward=(id:string)=>
  request<WalkForwardJob>("/live/research/walkforward/jobs/"+encodeURIComponent(id)+"/cancel",{
    method:"POST",
  });
