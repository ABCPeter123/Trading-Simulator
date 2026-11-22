import {request} from "./api";

export interface PaperExecution {
  broker:"legacy_research"|"wealthsimple"|"ibkr";
  account_type:"cash"|"margin";
  capital_currency:"USD"|"CAD";
  borrow_policy:"block_unverified"|"assume_available_research";
  fill_timing:"next_open"|"next_close";
  margin_rate_pct?:number;short_borrow_rate_pct?:number;
  slippage_bps?:number;fx_spread_bps?:number;
}
export interface PaperForwardOverview {
  id:string;source_job_id:string;created_at:string;updated_at:string;
  status:"active"|"paused"|"retired";model:string;symbols:string[];
  initial_capital:number;max_drawdown_pct:number;starting_session:string;last_session:string;
  observed_sessions:number;last_error:string|null;research_only:true;simulated_fills_only:true;
  cash:number;equity:number;positions:Record<string,number>;peak_equity:number;
  gross_exposure_pct:number;current_drawdown_pct:number;financing_paid:number;
  transaction_fees_paid:number;pending_execution:boolean;delay_sessions:number;
  news_sentiment_overlay?:boolean;
  audit_reference:{risk_free_pct:number;objectives:{cagr_pct:number|null;excess_sharpe:number|null}};
  execution_profile:PaperExecution & {rate_snapshot_date:string;manual_margin_override?:boolean};
  broker:{broker:string;account_type:string;pricing_date:string;currency:string;
    commission_assumption:string;borrowing_assumption:string;
    fx_assumption:string;fill_assumption:string};
  capital_currency:"USD"|"CAD";initial_amount:number;
  equity_cad:number|null;fx_rate:number|null;
  frozen_strategy_fingerprint:string|null;
  forward_benchmark:{
    status:"available"|"not_recorded";method:string;starting_session:string;
    last_session:string;observed_sessions:number;value_usd:number|null;
    return_pct:number|null;strategy_minus_benchmark_return_pct_points:number|null;
    benchmark_used_to_select_strategy:false;
  };
  fx_conversion_fee_usd:number;paper_pnl_cad:number|null;
  current_drawdown_cad_pct:number|null;
}
export interface PaperForwardDetail extends PaperForwardOverview {
  marks:{session:string;value:number;cash:number;gross_pct:number;
    drawdown_pct:number;financing_cost:number;fx_rate:number|null;value_cad:number|null;benchmark_value:number|null}[];
  fills:{session:string;symbol:string;action:string;quantity:number;
    price:number;fee:number;delay_sessions:number}[];
  statistics:{cagr_pct:number|null;excess_sharpe:number|null;
    annualized_volatility_pct:number|null;sessions:number};
  statistics_cad?:{cagr_pct:number|null;excess_sharpe:number|null;
    annualized_volatility_pct:number|null;sessions:number};
  drift:{status:string;cagr_gap_pct:number|null;sharpe_gap:number|null};
}
export const listPaperForward=()=>request<PaperForwardOverview[]>("/live/research/paper-forward");
export const getPaperForward=(id:string)=>request<PaperForwardDetail>(
  "/live/research/paper-forward/"+encodeURIComponent(id));
export const createPaperForward=(job_id:string,capital:number,max_drawdown_pct:number,
  execution?:PaperExecution,news_sentiment_overlay=false)=>
  request<PaperForwardOverview>("/live/research/paper-forward",{
    method:"POST",body:JSON.stringify({job_id,capital,max_drawdown_pct,execution,news_sentiment_overlay})});
export const evaluatePaperForward=(id:string)=>request<PaperForwardOverview>(
  "/live/research/paper-forward/"+encodeURIComponent(id)+"/evaluate",{method:"POST"});
export const changePaperForwardState=(id:string,status:"active"|"paused"|"retired")=>
  request<PaperForwardOverview>(
    "/live/research/paper-forward/"+encodeURIComponent(id),{
      method:"PUT",body:JSON.stringify({status})});
