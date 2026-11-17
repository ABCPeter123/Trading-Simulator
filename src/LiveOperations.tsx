import {useCallback,useEffect,useState} from "react";
import {Activity,AlertTriangle,Bell,Check,Clock3,PlayCircle,RefreshCw,Save,ShieldCheck,Wallet} from "lucide-react";
import {useI18n} from "./i18n";
import {listStrategies} from "./strategyLibraryApi";
import type {SavedStrategy} from "./strategyLibraryApi";
import {
  checkMachine,editConfirmedFill,getJournal,getMachineStatus,getNotifications,
  listDeployments,listFillRevisions,listMachineAlerts,listSignals,
  newDeployment,recordConfirmedFill,setAlertState,setDeploymentState,setSignalState,
} from "./liveMachineApi";
import type {Alert,ConfirmedFill,Deployment,FillDraft,Journal,MachineStatus,NotificationStatus,Signal} from "./liveMachineApi";
import "./liveOperations.css";

export type OperationsSection="dashboard"|"machine"|"journal"|"alerts";
const fmt=(n:number)=>Number.isFinite(n)?n.toLocaleString(undefined,{maximumFractionDigits:2}):"";
const when=(x:string|number|null)=>!x?"Never":new Date(typeof x==="number"?x*1000:x).toLocaleString();
const errorOf=(e:unknown)=>e instanceof Error?e.message:String(e);
const nowISO=()=>new Date().toISOString();
const emptyFill=():FillDraft=>({signal_id:null,asset_id:"",side:"buy",quantity:1,price:0,fee:0,
  currency:"USD",executed_at:nowISO(),broker_ref:"",notes:""});

function Summary({label,value,detail}:{label:string;value:string|number;detail?:string}){
  return <article className="ops-summary"><span>{label}</span><strong>{value}</strong>{detail&&<small>{detail}</small>}</article>;
}

export default function LiveOperations({section,initialSignal,onRecordSignal,onConsumed}:{
  section:OperationsSection;initialSignal?:Signal|null;
  onRecordSignal?:(signal:Signal)=>void;onConsumed?:()=>void;
}){
  const {t}=useI18n();
  const [status,setStatus]=useState<MachineStatus|null>(null);
  const [deployments,setDeployments]=useState<Deployment[]>([]);
  const [signals,setSignals]=useState<Signal[]>([]);
  const [journal,setJournal]=useState<Journal|null>(null);
  const [alerts,setAlerts]=useState<Alert[]>([]);
  const [notification,setNotification]=useState<NotificationStatus|null>(null);
  const [library,setLibrary]=useState<SavedStrategy[]>([]);
  const [selectedStrategy,setSelectedStrategy]=useState("");
  const [capital,setCapital]=useState("100000");
  const [monitorResolution,setMonitorResolution]=useState<"1d"|"1h"|"15m">("1d");
  const [allocation,setAllocation]=useState("10");
  const [dailyLimit,setDailyLimit]=useState("4");
  const [lossLimit,setLossLimit]=useState("5");
  const [running,setRunning]=useState(false);
  const [message,setMessage]=useState("");
  const [error,setError]=useState("");
  const [editing,setEditing]=useState<string|null>(null);
  const [draft,setDraft]=useState<FillDraft>(emptyFill);
  const [revisions,setRevisions]=useState<{previous:string;changed_at:string}[]>([]);

  const refresh=useCallback(async()=>{
    const results=await Promise.allSettled([
      getMachineStatus(),listDeployments(),listSignals(),getJournal(),listMachineAlerts(),getNotifications(),
      listStrategies("single"),listStrategies("portfolio"),
    ]);
    const [s,d,sg,j,a,n,single,portfolio]=results;
    if(s.status==="fulfilled")setStatus(s.value);
    if(d.status==="fulfilled")setDeployments(d.value);
    if(sg.status==="fulfilled")setSignals(sg.value);
    if(j.status==="fulfilled")setJournal(j.value);
    if(a.status==="fulfilled")setAlerts(a.value);
    if(n.status==="fulfilled")setNotification(n.value);
    if(single.status==="fulfilled"&&portfolio.status==="fulfilled"){
      const rows=[...single.value,...portfolio.value];
      setLibrary(rows);
      setSelectedStrategy(previous=>rows.some(x=>x.id===previous)?previous:(rows[0]?.id??""));
    }
    const rejected=results.find(x=>x.status==="rejected");
    if(rejected?.status==="rejected")throw rejected.reason;
  },[]);
  useEffect(()=>{
    let active=true;
    const load=()=>{void refresh().then(()=>{if(active)setError("");}).catch(e=>{if(active)setError(errorOf(e));});};
    load();
    const timer=setInterval(load,30000);
    return()=>{active=false;clearInterval(timer);};
  },[refresh]);

  async function mutate(fn:()=>Promise<unknown>,success:string){
    if(running)return;
    setRunning(true);setError("");setMessage("");
    try{await fn();await refresh();setMessage(t(success));}
    catch(e){setError(errorOf(e));}
    finally{setRunning(false);}
  }
  const pending=signals.filter(s=>s.status==="pending"||s.status==="acknowledged");
  function prefill(signal:Signal){
    if(section!=="journal"&&onRecordSignal){onRecordSignal(signal);return;}
    if(new Date(signal.expires_at).getTime()<Date.now()){setError(t("Signal expired. Revalidate before execution."));return;}
    const notional=signal.suggested_notional??0;
    setEditing(null);
    setDraft({signal_id:signal.id,asset_id:signal.asset_id,side:signal.side,
      quantity:signal.price_reference>0?Math.max(1,Math.floor(notional/signal.price_reference)):1,
      price:signal.price_reference,fee:0,currency:"USD",executed_at:nowISO(),broker_ref:"",notes:""});
    setMessage(t("Review all broker execution fields before saving."));
  }
  useEffect(()=>{
    if(section==="journal"&&initialSignal){
      prefill(initialSignal);
      onConsumed?.();
    }
  },[section,initialSignal?.id]);
  function edit(item:ConfirmedFill){
    setEditing(item.id);
    setDraft({signal_id:item.signal_id,asset_id:item.asset_id,side:item.side,quantity:item.quantity,
      price:item.price,fee:item.fee,currency:item.currency,executed_at:item.executed_at,
      broker_ref:item.broker_ref??"",notes:item.notes});
    setRevisions([]);
    void listFillRevisions(item.id).then(v=>setRevisions(v)).catch(()=>setRevisions([]));
  }
  async function saveFill(){
    if(!draft.asset_id.trim()){setError(t("Enter an instrument."));return;}
    const ready={...draft,asset_id:draft.asset_id.toLowerCase(),executed_at:new Date(draft.executed_at).toISOString()};
    await mutate(()=>editing?
      editConfirmedFill(editing,{...ready,signal_id:undefined} as Omit<FillDraft,"signal_id">):
      recordConfirmedFill(ready),editing?"Trade correction saved with revision history.":"Confirmed broker execution recorded.");
    setEditing(null);setDraft(emptyFill());setRevisions([]);
  }
  return <main className="ops-shell">
    <header className="ops-header">
      <div><p className="ops-kicker">{t("PRIVATE TRADING OPERATIONS")}</p>
        <h1>{t(section==="dashboard"?"Operations dashboard":section==="machine"?"Live strategy machine":
          section==="journal"?"Portfolio & trade journal":"Alerts & system health")}</h1>
        <p>{t("Human-confirmed execution. The machine never submits brokerage orders.")}</p>
      </div>
      <div className="ops-head-actions">
        <span className={"ops-indicator "+(status?.worker_online?"online":"offline")}>
          <Activity size={15}/>{t(status?.worker_online?"Worker online":"Worker offline")}
        </span>
        <button disabled={running} onClick={()=>void mutate(()=>refresh(), "Latest status loaded.")}>
          <RefreshCw size={15}/>{t("Refresh")}</button>
      </div>
    </header>
    {error&&<div className="ops-error" role="alert">{error}</div>}
    {message&&<div className="ops-message" role="status">{message}</div>}
    {!status&&<div className="ops-card">{t("Waiting for the private API. Start the private Python backend to use live operations.")}</div>}
    {(section==="dashboard"||section==="machine")&&<div className="ops-summary-grid">
      <Summary label={t("Active strategies")} value={status?.active_deployments??"–"}/>
      <Summary label={t("Pending signals")} value={status?.pending_signals??"–"}/>
      <Summary label={t("Critical alerts")} value={status?.critical_alerts??"–"}/>
      <Summary label={t("Confirmed realized P&L")} value={journal?(journal.realized_pnl===null?t("Multiple currencies"):fmt(journal.realized_pnl)):"–"} detail={t("Excludes unrealized positions and FX")}/>
    </div>}
    {section==="dashboard"&&<div className="ops-grid">
      <section className="ops-card">
        <h2><Bell size={18}/>{t("Actions requiring review")}</h2>
        {!pending.length?<p className="ops-muted">{t("No pending trade recommendations.")}</p>:pending.slice(0,6).map(s=><article className="ops-action" key={s.id}>
          <div><strong>{s.side.toUpperCase()} {s.asset_id.toUpperCase()}</strong>
            <small>{s.allocation_pct}% {t("reference capital")} · {t("Expires")} {when(s.expires_at)}</small></div>
          <button onClick={()=>prefill(s)}>{t("Record fill")}</button>
        </article>)}
        {pending.length>0&&<p className="ops-muted">{t("To record a recommendation, open the Trade Journal tab and verify the actual fill details.")}</p>}
      </section>
      <section className="ops-card">
        <h2><ShieldCheck size={18}/>{t("System readiness")}</h2>
        <div className="ops-line"><span>{t("Heartbeat")}</span><strong>{when(status?.heartbeat_at??null)}</strong></div>
        <div className="ops-line"><span>{t("Live broker integration")}</span><strong>{t("Disabled")}</strong></div>
        <div className="ops-line"><span>{t("Notification channels")}</span><strong>{notification?.channels.join(", ")||t("Not configured")}</strong></div>
        <div className="ops-line"><span>{t("Open critical incidents")}</span><strong>{alerts.filter(a=>a.severity==="critical"&&a.status==="open").length}</strong></div>
        <p className="ops-muted">{t("Worker must run independently of the browser. Failed or stale market data blocks new recommendations.")}</p>
      </section>
      <section className="ops-card ops-wide">
        <h2><Wallet size={18}/>{t("Confirmed positions")}</h2>
        <p className="ops-muted">{t("Actual manually recorded fills only. Prices are not marked to market here.")}</p>
        <div className="ops-table-wrap"><table><thead><tr><th>{t("Asset")}</th><th>{t("Quantity")}</th><th>{t("Average cost")}</th><th>{t("Realized P&L")}</th></tr></thead>
          <tbody>{(journal?.positions??[]).map(p=><tr key={p.asset_id}><td>{p.asset_id.toUpperCase()} ({p.currency})</td><td>{fmt(p.quantity)}</td><td>{fmt(p.average_cost)}</td><td>{fmt(p.realized_pnl)}</td></tr>)}</tbody></table></div>
      </section>
    </div>}
    {section==="machine"&&<div className="ops-grid">
      <section className="ops-card">
        <h2><PlayCircle size={18}/>{t("Deploy saved strategy")}</h2>
        <p className="ops-muted">{t("Uses the version already saved in the private strategy library. Deployments are frozen snapshots. Start with paper monitoring.")}</p>
        <label>{t("Saved strategy version")}
          <select value={selectedStrategy} onChange={e=>setSelectedStrategy(e.target.value)}>
            {!library.length&&<option value="">{t("Save a strategy in the Research tab first.")}</option>}
            {library.map(s=><option key={s.id} value={s.id}>{s.name} ({s.mode})</option>)}
          </select></label>
        <div className="ops-field-grid">
          <label>{t("Reference capital")}<input inputMode="decimal" type="number" min="100" value={capital} onChange={e=>setCapital(e.target.value)}/></label>
          <label>{t("Max allocation per signal (%)")}<input type="number" min="0.01" max="25" step=".5" value={allocation} onChange={e=>setAllocation(e.target.value)}/></label>
          <label>{t("Signal evaluation interval")}<select value={monitorResolution}
            onChange={e=>setMonitorResolution(e.target.value as "1d"|"1h"|"15m")}>
            <option value="1d">{t("Daily, previous completed session")}</option>
            <option value="1h">{t("Hourly, completed candle")}</option>
            <option value="15m">{t("15-minute, completed candle")}</option>
          </select></label>
          <label>{t("Daily signal limit")}<input type="number" min="1" max="20" value={dailyLimit} onChange={e=>setDailyLimit(e.target.value)}/></label>
          <label>{t("Realized-loss stop (%)")}<input type="number" min="0.5" max="25" step=".5" value={lossLimit} onChange={e=>setLossLimit(e.target.value)}/></label>
        </div>
        <button className="ops-primary" disabled={running||!selectedStrategy} onClick={()=>void mutate(
          ()=>newDeployment({strategy_id:selectedStrategy,state:"paper",capital:Number(capital),
          max_allocation_pct:Number(allocation),max_daily_signals:Number(dailyLimit),max_realized_loss_pct:Number(lossLimit),resolution:monitorResolution}),
          "Strategy deployed to paper signal monitoring.")}>
          {t("Deploy to paper monitoring")}</button>
        <p className="ops-muted">{t("Short selling, leverage and broker automation remain disabled until their risk models are validated.")}</p>
      </section>
      <section className="ops-card">
        <h2><Clock3 size={18}/>{t("Worker & evaluations")}</h2>
        <div className="ops-line"><span>{t("Last heartbeat")}</span><strong>{when(status?.heartbeat_at??null)}</strong></div>
        <div className="ops-line"><span>{t("Monitoring mode")}</span><strong>{t("Daily / hourly / 15-minute completed candles")}</strong></div>
        <button disabled={running} onClick={()=>void mutate(checkMachine,"Evaluation cycle complete (eligible trading hours only).")}>
          <RefreshCw size={15}/>{t("Evaluate now")}</button>
        <p className="ops-muted">{t("Daily monitoring uses completed prior-day bars. Intraday monitoring evaluates only closed 15-minute/hourly candles with fresh provider timestamps. Evaluations run during trading hours, with a 90-second worker cycle.")}</p>
        <div className="ops-recent">
          {(status?.recent_evaluations??[]).slice(0,8).map((e,i)=><div className="ops-line" key={i}>
            <span>{e.symbol.toUpperCase()} · {t(e.result)}</span><small>{when(e.evaluated_at)}</small>
          </div>)}
        </div>
      </section>
      <section className="ops-card ops-wide">
        <h2>{t("Deployed strategies")}</h2>
        {!deployments.length&&<p className="ops-muted">{t("No deployed strategies yet.")}</p>}
        {deployments.map(d=><div className="ops-deployment" key={d.id}>
          <div><strong>{d.name}</strong><small>{d.symbols.join(", ").toUpperCase()} · {d.resolution??"1d"} · {t(d.state)} · {t("Last evaluation")}: {when(d.last_evaluated_at)} · {t("Loss stop")}: {d.max_realized_loss_pct}%</small>
            {d.last_error&&<small className="ops-danger">{t("Data check failed. No recommendation generated.")}</small>}</div>
          <div className="ops-action-buttons">
            {d.state!=="retired"&&<button disabled={running} onClick={()=>void mutate(
              ()=>setDeploymentState(d.id,d.state==="paused"?"paper":"paused"),
              "Deployment state updated.")}>{d.state==="paused"?t("Resume paper"):t("Pause")}</button>}
            {d.state==="paper"&&<button disabled={running} onClick={()=>void mutate(
              ()=>setDeploymentState(d.id,"live-monitor"),
              "Live monitoring enabled. Execution remains manual.")}>{t("Live monitor")}</button>}
            {d.state!=="retired"&&<button disabled={running} onClick={()=>{if(window.confirm(t("Retire this deployment permanently?")))void mutate(()=>setDeploymentState(d.id,"retired"),"Deployment retired.");}}>{t("Retire")}</button>}
          </div>
        </div>)}
      </section>
      <section className="ops-card ops-wide">
        <h2>{t("Recent strategy recommendations")}</h2>
        <div className="ops-table-wrap"><table><thead><tr><th>{t("Symbol / action")}</th><th>{t("Cap")}</th><th>{t("Reference price")}</th><th>{t("Status")}</th><th>{t("Expiry")}</th><th>{t("Actions")}</th></tr></thead>
          <tbody>{signals.map(s=><tr key={s.id}>
            <td><strong>{s.asset_id.toUpperCase()} · {s.side.toUpperCase()}</strong><small>{s.rationale}</small></td>
            <td>{s.allocation_pct}%</td><td>{fmt(s.price_reference)}</td><td>{t(s.status)}</td><td>{when(s.expires_at)}</td>
            <td><div className="ops-action-buttons">
              {(s.status==="pending"||s.status==="acknowledged")&&<>
                {s.status==="pending"&&<button disabled={running} onClick={()=>void mutate(()=>setSignalState(s.id,"acknowledged"),"Signal acknowledged.")}>{t("Acknowledge")}</button>}
                <button onClick={()=>prefill(s)}>{t("Record fill")}</button>
                <button disabled={running} onClick={()=>void mutate(()=>setSignalState(s.id,"skipped"),"Signal skipped.")}>{t("Skip")}</button>
              </>}
            </div></td>
          </tr>)}</tbody></table></div>
      </section>
    </div>}
    {section==="journal"&&<div className="ops-grid">
      <section className="ops-card">
        <h2><Save size={18}/>{t(editing?"Correct recorded trade":"Record broker execution")}</h2>
        <p className="ops-muted">{t("Prefill from a recommendation or enter any broker trade manually. Every field is editable and corrections retain prior versions.")}</p>
        <form onSubmit={e=>{e.preventDefault();void saveFill();}}>
          <div className="ops-field-grid">
            <label>{t("Instrument")}<input required value={draft.asset_id} onChange={e=>setDraft({...draft,asset_id:e.target.value})}/></label>
            <label>{t("Side")}<select value={draft.side} onChange={e=>setDraft({...draft,side:e.target.value as "buy"|"sell"})}><option value="buy">{t("Buy")}</option><option value="sell">{t("Sell")}</option></select></label>
            <label>{t("Quantity")}<input required type="number" min=".00000001" step="any" value={draft.quantity} onChange={e=>setDraft({...draft,quantity:Number(e.target.value)})}/></label>
            <label>{t("Actual fill price")}<input required type="number" min=".00000001" step="any" value={draft.price} onChange={e=>setDraft({...draft,price:Number(e.target.value)})}/></label>
            <label>{t("Fee")}<input required type="number" min="0" step="any" value={draft.fee} onChange={e=>setDraft({...draft,fee:Number(e.target.value)})}/></label>
            <label>{t("Currency")}<select value={draft.currency} onChange={e=>setDraft({...draft,currency:e.target.value})}>{["USD","CAD","EUR","GBP"].map(x=><option key={x}>{x}</option>)}</select></label>
            <label>{t("Execution timestamp (UTC)")}<input required type="datetime-local" value={new Date(draft.executed_at).toISOString().slice(0,16)}
              onChange={e=>setDraft({...draft,executed_at:new Date(e.target.value+"Z").toISOString()})}/></label>
            <label>{t("Broker reference")}<input value={draft.broker_ref} onChange={e=>setDraft({...draft,broker_ref:e.target.value})}/></label>
          </div>
          <label>{t("Notes")}<textarea rows={2} value={draft.notes} onChange={e=>setDraft({...draft,notes:e.target.value})}/></label>
          {draft.signal_id&&<p className="ops-muted">{t("Linked suggestion")}: {draft.signal_id.slice(0,8)} · {t("Verify executed price and size with broker.")}</p>}
          <div className="ops-action-buttons"><button className="ops-primary" disabled={running} type="submit"><Check size={15}/>{t(editing?"Save audited correction":"Save confirmed execution")}</button>
            <button type="button" onClick={()=>{setEditing(null);setDraft(emptyFill());setRevisions([]);}}>{t("Clear")}</button></div>
        </form>
        {!!revisions.length&&<div className="ops-revisions">
          <h3>{t("Previous revisions")}</h3>{revisions.map((r,i)=><p key={i}><small>{when(r.changed_at)}</small><code>{r.previous}</code></p>)}
        </div>}
      </section>
      <section className="ops-card">
        <h2><Wallet size={18}/>{t("Confirmed portfolio summary")}</h2>
        <div className="ops-line"><span>{t("Confirmed fills")}</span><strong>{journal?.fills.length??0}</strong></div>
        <div className="ops-line"><span>{t("Realized P&L")}</span><strong>{journal?.realized_pnl===null?t("Multiple currencies"):fmt(journal?.realized_pnl??0)}</strong></div>
        <p className="ops-muted">{t("No brokerage connection. Cost basis is weighted-average, long-only, without FX conversion or unrealized market marks. Keep currencies separate.")}</p>
        {Object.entries(journal?.realized_by_currency??{}).map(([currency,value])=><div className="ops-line" key={currency}><span>{currency} {t("Realized P&L")}</span><strong>{fmt(value)}</strong></div>)}
        {(journal?.positions??[]).filter(p=>p.quantity>0).map(p=><div key={p.asset_id} className="ops-line"><span>{p.asset_id.toUpperCase()} ({p.currency})</span><strong>{fmt(p.quantity)} @ {fmt(p.average_cost)}</strong></div>)}
      </section>
      <section className="ops-card ops-wide">
        <h2>{t("Execution versus recommendation")}</h2>
        <p className="ops-muted">{t("Review execution delays and price deviations from the signal reference. These differences can explain why actual results diverge from backtests.")}</p>
        {!(journal?.execution_reviews??[]).length&&<p className="ops-muted">{t("No confirmed trades linked to recommendations yet.")}</p>}
        <div className="ops-table-wrap"><table><thead><tr>
          <th>{t("Asset")}</th><th>{t("Suggested price")}</th><th>{t("Actual fill price")}</th>
          <th>{t("Price difference")}</th><th>{t("Delay (hours)")}</th><th>{t("Exceptions")}</th>
        </tr></thead><tbody>{(journal?.execution_reviews??[]).map(x=><tr key={x.fill_id}>
          <td>{x.asset_id.toUpperCase()} · {x.side.toUpperCase()}</td><td>{fmt(x.reference_price)}</td>
          <td>{fmt(x.actual_price)}</td><td>{fmt(x.price_deviation_pct)}%</td>
          <td>{fmt(x.execution_delay_hours)}</td>
          <td>{[x.after_signal_expiry?t("Late fill"):"",x.different_asset_or_side?t("Changed action"):""].filter(Boolean).join(", ")||t("Within window")}</td>
        </tr>)}</tbody></table></div>
      </section>
      <section className="ops-card ops-wide">
        <h2>{t("Permanent execution journal")}</h2>
        <div className="ops-table-wrap"><table><thead><tr><th>{t("Execution time")}</th><th>{t("Asset")}</th><th>{t("Side")}</th><th>{t("Quantity")}</th><th>{t("Price")}</th><th>{t("Fee")}</th><th>{t("Actions")}</th></tr></thead>
          <tbody>{(journal?.fills??[]).map(f=><tr key={f.id}><td>{when(f.executed_at)}</td><td>{f.asset_id.toUpperCase()}</td><td>{t(f.side)}</td><td>{fmt(f.quantity)}</td><td>{fmt(f.price)} {f.currency}</td><td>{fmt(f.fee)}</td><td><button onClick={()=>edit(f)}>{t("Edit / audit")}</button></td></tr>)}</tbody></table></div>
      </section>
    </div>}
    {section==="alerts"&&<div className="ops-grid">
      <section className="ops-card">
        <h2><Bell size={18}/>{t("Notification delivery")}</h2>
        <div className="ops-line"><span>{t("Configured channels")}</span><strong>{notification?.channels.join(", ")||t("None")}</strong></div>
        <p className="ops-muted">{t("Set the Discord webhook or SMTP credentials in your local environment. Secrets are never committed to GitHub or Vercel.")}</p>
        <p className="ops-muted">{t("Critical incidents repeat every 15 minutes until acknowledged. Routine alerts are deduplicated.")}</p>
        {(notification?.deliveries??[]).slice(0,8).map((d,i)=><div key={i} className="ops-line"><span>{d.channel} · {d.key.slice(0,25)}</span><small>{d.last_error||when(d.delivered_at)}</small></div>)}
      </section>
      <section className="ops-card">
        <h2><ShieldCheck size={18}/>{t("Safety controls")}</h2>
        <div className="ops-line"><span>{t("Automated broker orders")}</span><strong>{t("Disabled")}</strong></div>
        <div className="ops-line"><span>{t("Signal allocation limit")}</span><strong>25% {t("hard ceiling")}</strong></div>
        <div className="ops-line"><span>{t("Realized-loss stop")}</span><strong>{t("Pause and alert")}</strong></div>
        <div className="ops-line"><span>{t("Incomplete/stale candles")}</span><strong>{t("Fail closed")}</strong></div>
        <div className="ops-line"><span>{t("Strategy changes")}</span><strong>{t("Versioned deployment")}</strong></div>
        <div className="ops-line"><span>{t("Live strategy failure")}</span><strong>{t("Alert and pause recommendation")}</strong></div>
        <p className="ops-muted">{t("Leverage, short sales, broker reconciliation, advanced margin stress and automatic execution need additional validation before live capital use.")}</p>
      </section>
      <section className="ops-card ops-wide">
        <h2><AlertTriangle size={18}/>{t("Incidents and alerts")}</h2>
        {!alerts.length&&<p className="ops-muted">{t("No recorded incidents.")}</p>}
        {alerts.map(a=><article className={"ops-alert "+a.severity} key={a.id}>
          <div><strong>{t(a.severity.toUpperCase())} · {a.title}</strong><p>{a.detail}</p><small>{when(a.last_seen_at)} · {t(a.status)}</small></div>
          {a.status==="open"&&<div className="ops-action-buttons">
            <button disabled={running} onClick={()=>void mutate(()=>setAlertState(a.id,"acknowledged"),"Alert acknowledged.")}>{t("Acknowledge")}</button>
            <button disabled={running} onClick={()=>void mutate(()=>setAlertState(a.id,"resolved"),"Alert resolved.")}>{t("Resolve")}</button>
          </div>}
        </article>)}
      </section>
    </div>}
    <footer className="ops-footer">{t("Private local data. Signals are recommendations, not trades. Live trading cannot guarantee profit.")}</footer>
  </main>;
}
