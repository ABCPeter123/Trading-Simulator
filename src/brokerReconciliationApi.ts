import {request} from "./api";

export interface NormalizedStatementTrade{
  symbol:string;side:"buy"|"sell";trade_date:string;quantity:number;
  price:number;currency:"USD";fee?:number;broker_ref?:string;
  executed_at?:string;
}
export interface ReconciliationRow {
  statement_row:number;symbol:string;side:"buy"|"sell";trade_date:string;
  status:"matched"|"matched_with_differences"|"not_in_journal"|
    "ambiguous_broker_reference"|"ambiguous_field_match"|"duplicate_statement_row";
  matched_fill_id:string|null;match_type:string|null;differences:string[];
  statement_price:number;statement_quantity:number;statement_fee:number|null;
  journal_price:number|null;journal_quantity:number|null;journal_fee:number|null;
}
export interface ReconciliationResult{
  read_only:true;import_persisted:false;currency:"USD";
  date_range:{start:string;end:string};
  summary:{statement_rows:number;journal_rows_in_date_range:number;
    matched:number;matched_with_differences:number;not_in_journal:number;
    ambiguous:number;duplicate_statement_rows:number;journal_not_in_import:number};
  reviews:ReconciliationRow[];
  journal_not_in_import:{fill_id:string;symbol:string;side:string;trade_date:string}[];
  limitations:string;
}
export const compareBrokerStatement=(rows:NormalizedStatementTrade[])=>
  request<ReconciliationResult>("/live/journal/reconcile",{
    method:"POST",body:JSON.stringify({rows})});
