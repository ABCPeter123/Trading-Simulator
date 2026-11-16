import { request } from "./api";
export interface ScenarioPoint {
  step:number;p05:number;p25:number;median:number;p75:number;p95:number;
}
export interface ScenarioResult {
  asset_id:string;as_of:number;resolution:string;spot:number;
  horizon:number;lookback:number;paths_count:number;seed:number;
  mu_log_per_bar:number;sigma_per_bar:number;observations:number;
  prob_up_model_pct:number;prob_up_simulated_pct:number;
  expected_terminal:number;median_terminal:number;
  quantiles:ScenarioPoint[];paths:number[][];limitations:string;method:string;
}
export const getScenarios=(mode:"single"|"portfolio",run_id:string,asset_id:string,horizon:number,lookback:number)=>
  request<ScenarioResult>("/research/scenarios", {method:"POST",
    body:JSON.stringify({mode,run_id,asset_id,horizon,lookback})});
export interface OptionPrices {call:number;put:number;method:string;not_a_price_forecast:boolean}
export const priceEuropeanOption=(params:{spot:number;strike:number;maturity_years:number;volatility_annual:number;risk_free_rate:number})=>
  request<OptionPrices>("/research/black-scholes",{method:"POST",body:JSON.stringify(params)});
