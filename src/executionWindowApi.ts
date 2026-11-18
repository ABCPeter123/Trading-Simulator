import {request} from "./api";

export interface ExecutionScenario {
  delay_minutes:number;window_hours:number;capacity_fraction:number;
  status:"awaiting_completed_bar"|"no_completed_bar_observed"|
    "volume_unavailable"|"notional_unavailable"|
    "capacity_observed"|"partial_capacity_observed";
  first_bar:string|null;observed_at:string|null;
  hours_since_signal:number|null;estimated_price_usd:number|null;
  price_change_pct:number|null;requested_shares:number|null;
  capacity_shares:number|null;estimated_fillable_shares:number|null;
  capacity_pct:number|null;retrospective:boolean|null;regular_session_only:true;
}
export interface ExecutionWindowObservation {
  signal_id:string;symbol:string;side:"buy"|"sell";
  signal_at:string;window_end:string;observed_at:string;
  status:"window_active"|"window_elapsed";
  scenarios:ExecutionScenario[];
  source:string;executed:false;limitation:string;
}
export const getExecutionWindows=()=>request<ExecutionWindowObservation[]>(
  "/live/execution-windows");
export const checkExecutionWindows=()=>request<{evaluated_signals:number;data_unavailable:number}>(
  "/live/execution-windows/check",{method:"POST"});
