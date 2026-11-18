import {request} from "./api";

export interface PaperForwardOverview {
  id:string;source_job_id:string;created_at:string;updated_at:string;
  status:"active"|"paused"|"retired";model:string;symbols:string[];
  initial_capital:number;max_drawdown_pct:number;starting_session:string;last_session:string;
  observed_sessions:number;last_error:string|null;research_only:true;simulated_fills_only:true;
  cash:number;equity:number;positions:Record<string,number>;peak_equity:number;
  gross_exposure_pct:number;current_drawdown_pct:number;financing_paid:number;
  transaction_fees_paid:number;pending_execution:boolean;delay_sessions:number;
  audit_reference:{risk_free_pct:number;objectives:{cagr_pct:number|null;excess_sharpe:number|null}};
}
export interface PaperForwardDetail extends PaperForwardOverview {
  marks:{session:string;value:number;cash:number;gross_pct:number;
    drawdown_pct:number;financing_cost:number}[];
  fills:{session:string;symbol:string;action:string;quantity:number;
    price:number;fee:number;delay_sessions:number}[];
  statistics:{cagr_pct:number|null;excess_sharpe:number|null;
    annualized_volatility_pct:number|null;sessions:number};
  drift:{status:string;cagr_gap_pct:number|null;sharpe_gap:number|null};
}
export const listPaperForward=()=>request<PaperForwardOverview[]>("/live/research/paper-forward");
export const getPaperForward=(id:string)=>request<PaperForwardDetail>(
  "/live/research/paper-forward/"+encodeURIComponent(id));
export const createPaperForward=(job_id:string,capital:number,max_drawdown_pct:number)=>
  request<PaperForwardOverview>("/live/research/paper-forward",{
    method:"POST",body:JSON.stringify({job_id,capital,max_drawdown_pct})});
export const evaluatePaperForward=(id:string)=>request<PaperForwardOverview>(
  "/live/research/paper-forward/"+encodeURIComponent(id)+"/evaluate",{method:"POST"});
export const changePaperForwardState=(id:string,status:"active"|"paused"|"retired")=>
  request<PaperForwardOverview>(
    "/live/research/paper-forward/"+encodeURIComponent(id),{
      method:"PUT",body:JSON.stringify({status})});
