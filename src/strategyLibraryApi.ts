import {request} from "./api";

export interface SavedStrategy {
  id:string;name:string;mode:"single"|"portfolio";code:string;
  symbols:string[];source_run_id:string|null;
  source:"manual"|"activated";created_at:string;
}
export const listStrategies=(mode:"single"|"portfolio")=>
  request<SavedStrategy[]>(`/strategies?mode=${mode}`);
export const saveStrategy=(value:{name:string;mode:"single"|"portfolio";code:string;symbols:string[];source_run_id:string})=>
  request<SavedStrategy>("/strategies",{method:"POST",body:JSON.stringify(value)});
export const deleteStrategy=(id:string)=>
  request<{deleted:boolean;id:string}>(`/strategies/${encodeURIComponent(id)}`,{method:"DELETE"});
