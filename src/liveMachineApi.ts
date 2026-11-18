import {request} from "./api";

export interface Deployment {
  id:string;strategy_id:string;name:string;mode:"single"|"portfolio"|"portfolio_model";
  symbols:string[];state:"paper"|"live-monitor"|"paused"|"retired";
  capital:number;max_allocation_pct:number;max_realized_loss_pct:number;max_daily_signals:number;
  resolution:"1d"|"1h"|"15m";
  created_at:string;updated_at:string;last_evaluated_at:string|null;last_error:string|null;
}
export interface Signal {
  id:string;deployment_id:string;evaluation_id:string;source_symbol:string;
  asset_id:string;side:"buy"|"sell";allocation_pct:number;
  suggested_notional:number|null;price_reference:number;data_time:number;
  created_at:string;expires_at:string;status:string;
  rationale:string;forecast_prob_up_pct:number|null;
}
export interface ConfirmedFill {
  id:string;signal_id:string|null;asset_id:string;side:"buy"|"sell";
  quantity:number;price:number;fee:number;currency:string;executed_at:string;
  broker_ref:string|null;notes:string;created_at:string;updated_at:string;
}
export interface Alert {
  id:string;key:string;severity:"info"|"warning"|"critical";title:string;
  detail:string;status:string;created_at:string;last_seen_at:string;
  last_sent_at:string|null;send_attempts:number;last_delivery_error:string|null;
}
export interface MachineStatus {
  worker_online:boolean;heartbeat_age_seconds:number|null;heartbeat_at:string|null;
  active_deployments:number;pending_signals:number;critical_alerts:number;
  recent_evaluations:{deployment_id:string;symbol:string;bar_time:number;result:string;evaluated_at:string}[];
  execution_mode:string;broker_connected:boolean;
}
export interface Journal {
  fills:ConfirmedFill[];positions:{asset_id:string;currency:string;quantity:number;average_cost:number;realized_pnl:number}[];
  realized_pnl:number|null;realized_by_currency:Record<string,number>;note:string;
  execution_reviews:{fill_id:string;signal_id:string;asset_id:string;side:string;
    reference_price:number;actual_price:number;price_deviation_pct:number;
    execution_delay_hours:number;after_signal_expiry:boolean;different_asset_or_side:boolean;
    suggested_notional:number|null;actual_notional:number}[];
}
export interface NotificationStatus {
  channels:string[];
  deliveries:{key:string;channel:string;delivered_at:string|null;attempts:number;last_error:string|null}[];
}
export type FillDraft = {
  signal_id:string|null;asset_id:string;side:"buy"|"sell";quantity:number;
  price:number;fee:number;currency:string;executed_at:string;broker_ref:string;notes:string;
};
export const getMachineStatus=()=>request<MachineStatus>("/live/status");
export const listDeployments=()=>request<Deployment[]>("/live/deployments");
export const newDeployment=(body:{strategy_id:string;state:"paper"|"live-monitor";capital:number;max_allocation_pct:number;max_realized_loss_pct:number;max_daily_signals:number;resolution:"1d"|"1h"|"15m"})=>
  request<Deployment>("/live/deployments",{method:"POST",body:JSON.stringify(body)});
export const setDeploymentState=(id:string,state:Deployment["state"])=>
  request<Deployment>("/live/deployments/"+encodeURIComponent(id),{method:"PUT",body:JSON.stringify({state})});
export const checkMachine=()=>request<MachineStatus>("/live/evaluate",{method:"POST"});
export const listSignals=()=>request<Signal[]>("/live/signals");
export const setSignalState=(id:string,status:"acknowledged"|"skipped"|"expired")=>
  request<Signal>("/live/signals/"+encodeURIComponent(id),{method:"PUT",body:JSON.stringify({status})});
export const getJournal=()=>request<Journal>("/live/journal");
export const recordConfirmedFill=(fill:FillDraft)=>request<ConfirmedFill>("/live/journal",{method:"POST",body:JSON.stringify(fill)});
export const editConfirmedFill=(id:string,fill:Omit<FillDraft,"signal_id">)=>
  request<ConfirmedFill>("/live/journal/"+encodeURIComponent(id),{method:"PUT",body:JSON.stringify(fill)});
export const listFillRevisions=(id:string)=>request<{id:string;fill_id:string;previous:string;changed_at:string}[]>("/live/journal/"+encodeURIComponent(id)+"/revisions");
export const listMachineAlerts=()=>request<Alert[]>("/live/alerts");
export const setAlertState=(id:string,status:"acknowledged"|"resolved")=>
  request<Alert>("/live/alerts/"+encodeURIComponent(id),{method:"PUT",body:JSON.stringify({status})});
export const getNotifications=()=>request<NotificationStatus>("/live/notifications");
