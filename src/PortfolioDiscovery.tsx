import {useCallback,useEffect,useState} from "react";
import {Activity,BarChart3,ChartNoAxesCombined,RefreshCw,ShieldCheck} from "lucide-react";
import {request} from "./api";
import {useI18n} from "./i18n";
import "./portfolioDiscovery.css";

interface Point {time:number;value:number}
interface Trade {time:number;symbol:string;side:string;quantity:number;price:number;fee:number;notional:number}
interface Rebalance {time:number;weights:Record<string,number>;cash_pct:number}
interface Metrics {
  return_pct:number;max_drawdown_pct:number;sharpe:number|null;sortino:number|null;
  annualized_volatility_pct:number|null;trades:number;turnover_pct:number;
  fees:number;cash_pct:number;average_invested_pct:number;effective_positions:number;
  starting_capital:number;ending_equity:number;final_weights_pct:Record<string,number>;
  equity_curve:Point[];executions:Trade[];rebalances:Rebalance[];
}
type CompactMetrics=Omit<Metrics,"equity_curve"|"executions"|"rebalances">;
interface Candidate {model:string;score:number;qualified:boolean;train:CompactMetrics;validation:CompactMetrics}
interface PortfolioStudy {
  id:string;created_at:string;basket:string[];groups:Record<string,string[]>;
  sources:Record<string,string>;first_session:string;last_session:string;
  sessions:number;train_sessions:number;validation_sessions:number;test_sessions:number;
  warmup_sessions:number;max_drawdown_limit_pct:number;max_position_pct:number;
  candidate_count:number;eligible_count:number;candidates:Candidate[];
  selected:null|{model:string;train:Metrics;validation:Metrics;held_out_test:Metrics;
    held_out_equal_weight_benchmark:Metrics;warning:string};
  correlation_matrix:Record<string,Record<string,number|null>>;
  test_used_for_selection:boolean;assumptions:string;qualification_note:string;
}
interface Prior {id:string;created_at:string;basket:string[];selected:string|null}
interface ResearchJob {
  id:string;kind:string;status:"queued"|"running"|"completed"|"failed"|"cancelled";
  symbols:string[];max_drawdown_pct:number;max_position_pct:number;progress:number;
  stage:string;result_run_id:string|null;error_code:string|null;created_at:string;
  updated_at:string;started_at:string|null;finished_at:string|null;
}
type DetailTab="performance"|"allocation"|"executions";
const modelLabels:Record<string,string>={
  equal_weight:"Equal weight",inverse_volatility:"Inverse volatility",
  trend_filter:"Trend filtered",relative_momentum:"Relative momentum",
  volatility_target:"Volatility target",
};
const descriptions:Record<string,string>={
  equal_weight:"Equal capital targets, monthly rebalance.",
  inverse_volatility:"More weight to less volatile instruments.",
  trend_filter:"Invest only in assets above their trailing 126-session mean.",
  relative_momentum:"Select strongest positive momentum assets.",
  volatility_target:"Inverse-volatility, estimated 12% annual risk budget.",
};
const label=(x:string)=>modelLabels[x]??x;
const pct=(v:number|null|undefined)=>v===null||v===undefined?"N/A":v.toFixed(2)+"%";
const dollars=(v:number)=>v.toLocaleString(undefined,{style:"currency",currency:"USD",maximumFractionDigits:2});
const num=(v:number|null)=>v===null?"N/A":v.toFixed(2);
const dt=(x:string|number)=>new Date(typeof x==="number"?x*1000:x).toLocaleString();

function Curves({chosen,benchmark}:{chosen:Point[];benchmark:Point[]}){
  if(chosen.length<2)return <p>No available test curve.</p>;
  const tracks=[{points:chosen,color:"#67dfbc",name:"Selected model"},
    {points:benchmark,color:"#e8af63",name:"Equal-weight baseline"}];
  const values=tracks.flatMap(t=>t.points.map(p=>p.value));
  const lo=Math.min(...values),hi=Math.max(...values),span=Math.max(1,hi-lo);
  const path=(series:Point[])=>series.map((p,i)=>{
    const x=42+912*i/Math.max(1,series.length-1);
    const y=194-155*(p.value-lo)/span;
    return (i===0?"M":"L")+x.toFixed(1)+","+y.toFixed(1);
  }).join(" ");
  return <div className="pd-chart">
    <div className="pd-chart-legend"><span>Selected model</span><span>Equal-weight baseline</span></div>
    <svg role="img" aria-label="Held-out portfolio equity versus equal-weight baseline"
      viewBox="0 0 1000 230" preserveAspectRatio="none">
      <path d="M42,194 H954" stroke="#334454" fill="none"/>
      {tracks.map(t=><path key={t.name} d={path(t.points)} stroke={t.color}
        strokeWidth="2.6" fill="none" strokeLinejoin="round"/>)}
      <text x="46" y="24" fontSize="16" fill="#abbfcc">{dollars(hi)}</text>
      <text x="46" y="215" fontSize="16" fill="#abbfcc">{dollars(lo)}</text>
    </svg>
    <div className="pd-chart-times"><span>{dt(chosen[0].time)}</span>
      <span>{dt(chosen[chosen.length-1].time)}</span></div>
  </div>;
}

import {validatedPercent} from "./validatedPercent";

export default function PortfolioDiscovery(){
  const {t}=useI18n();
  const [symbols,setSymbols]=useState("spy, qqq, ief, gld, eem, vnq");
  const [drawdown,setDrawdown]=useState("25");
  const [maxPosition,setMaxPosition]=useState("35");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [selected,setSelected]=useState<PortfolioStudy|null>(null);
  const [runs,setRuns]=useState<Prior[]>([]);
  const [jobs,setJobs]=useState<ResearchJob[]>([]);
  const [recentJob,setRecentJob]=useState<string|null>(null);
  const [tab,setTab]=useState<DetailTab>("performance");
  const refresh=useCallback(async()=>{
    const [saved,queued]=await Promise.all([
      request<Prior[]>("/live/research/portfolio/runs"),
      request<ResearchJob[]>("/live/research/portfolio/jobs"),
    ]);
    setRuns(saved);setJobs(queued);
  },[]);
  useEffect(()=>{void refresh().catch(e=>setError(String(e)));},[refresh]);
  useEffect(()=>{
    // The queue and its actual computation run on the laptop, not here.
    // Poll only while the tab is open; closing the browser never cancels work.
    const timer=window.setInterval(()=>{
      void request<ResearchJob[]>("/live/research/portfolio/jobs").then(setJobs).catch(()=>{});
    },5000);
    return ()=>window.clearInterval(timer);
  },[]);
  useEffect(()=>{
    if(!recentJob)return;
    const job=jobs.find(x=>x.id===recentJob);
    if(job?.status==="completed"&&job.result_run_id){
      const runId=job.result_run_id;
      setRecentJob(null);
      void request<PortfolioStudy>("/live/research/portfolio/runs/"+encodeURIComponent(runId))
        .then(study=>{setSelected(study);setTab("performance");void refresh().catch(()=>{});})
        .catch(e=>setError(String(e)));
    }else if(job?.status==="failed"||job?.status==="cancelled"){
      setRecentJob(null);
    }
  },[jobs,recentJob,refresh]);
  async function compare(){
    setBusy(true);setError("");
    const basket=symbols.split(/[,;\s]+/).map(x=>x.trim().toLowerCase()).filter(Boolean);
    try{
      if(basket.length<2||basket.length>10)throw new Error("Enter between 2 and 10 instruments.");
      const max_drawdown_pct=validatedPercent(drawdown,"Validation drawdown limit",1,50);
      const max_position_pct=validatedPercent(maxPosition,"Maximum single position",5,50);
      const job=await request<ResearchJob>("/live/research/portfolio/jobs",{
        method:"POST",body:JSON.stringify({symbols:basket,
          max_drawdown_pct,max_position_pct}),
      });
      setRecentJob(job.id);
      setJobs(items=>[job,...items.filter(x=>x.id!==job.id)]);
      await refresh();
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function open(runId:string){
    setBusy(true);setError("");
    try{setSelected(await request<PortfolioStudy>(
      "/live/research/portfolio/runs/"+encodeURIComponent(runId)));
      setTab("performance");}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function cancelJob(id:string){
    setError("");
    try{
      const cancelled=await request<ResearchJob>(
        "/live/research/portfolio/jobs/"+encodeURIComponent(id)+"/cancel",{method:"POST"});
      setJobs(items=>items.map(x=>x.id===id?cancelled:x));
      if(recentJob===id)setRecentJob(null);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
  }
  const chosen=selected?.selected;
  const metrics=chosen?.held_out_test;
  return <div className="pd-shell">
    <header className="pd-header">
      <div><h2>{t("Portfolio strategy comparison")}</h2>
        <p>{t("Analyze a basket, not one ticker. The models share cash and risk limits. Held-out history is inspected after validation selection.")}</p>
      </div>
      <span className="pd-private"><ShieldCheck size={15}/>{t("Private local research")}</span>
    </header>
    {error&&<div className="ops-error" role="alert">{error}</div>}
    <div className="pd-layout">
      <section className="disc-card pd-setup">
        <h3><Activity size={17}/>{t("Portfolio basket")}</h3>
        <label>{t("Assets, separated by commas. Choose 2 to 10.")}
          <textarea rows={3} value={symbols} onChange={e=>setSymbols(e.target.value)}
            spellCheck={false} placeholder="spy, ief, gld, eem, btcusd"/></label>
        <p className="disc-muted">{t("Supports USD/CAD stocks and ETFs, plus USD cryptocurrencies. Canadian securities are converted using the previous completed USD/CAD daily FX close. Crypto weekends are excluded when mixed with stock assets.")}</p>
        <label>{t("Validation drawdown limit (%)")}
          <input type="number" min="1" max="50" value={drawdown}
            onChange={e=>setDrawdown(e.target.value)}/></label>
        <label>{t("Maximum single position (%)")}
          <input type="number" min="5" max="50" value={maxPosition}
            onChange={e=>setMaxPosition(e.target.value)}/></label>
        <button className="disc-primary" disabled={busy} onClick={()=>void compare()}>
          <ChartNoAxesCombined size={16}/>{busy?t("Queuing study..."):t("Queue research on laptop")}</button>
        <p className="disc-muted">{t("Five models. Monthly rebalancing, spread, slippage, commission. Selection uses training and validation only. Nothing deploys automatically.")}</p>
        <h3>{t("Laptop research queue")}</h3>
        {!jobs.length&&<p className="disc-muted">{t("No queued research jobs.")}</p>}
        <div className="pd-jobs" role="region" aria-label={t("Laptop research queue")}>
        {jobs.slice(0,20).map(job=><div className="pd-job" key={job.id}>
          <div className="pd-job-top">
            <strong>{job.symbols.map(s=>s.toUpperCase()).join(" · ")}</strong>
            <span className={"pd-job-status pd-"+job.status}>{t(job.status)}</span>
          </div>
          <div className="pd-job-stage">{t(job.stage)} · {dt(job.created_at)}</div>
          {(job.status==="queued"||job.status==="running")&&
            <div className="pd-job-meter" role="progressbar" aria-label={t("Research progress")}
              aria-valuenow={job.progress} aria-valuemin={0} aria-valuemax={100}>
              <i style={{width:pct(job.progress)}}/>
            </div>}
          <div className="pd-job-actions">
            {job.status==="completed"&&job.result_run_id&&
              <button disabled={busy} onClick={()=>void open(job.result_run_id!)}>{t("Open results")}</button>}
            {(job.status==="queued"||job.status==="running")&&
              <button disabled={busy} onClick={()=>void cancelJob(job.id)}>{t("Cancel research")}</button>}
            {job.status==="failed"&&<small>{t("Research failed")}: {job.error_code??t("Unknown error")}</small>}
          </div>
        </div>)}
        </div>
        <p className="disc-muted">{t("Jobs run independently on your Windows laptop. You can close this browser and return later. The laptop and private bridge must stay running.")}</p>
        <h3>{t("Previous portfolio studies")}</h3>
        {!runs.length&&<p className="disc-muted">{t("No previous portfolio study.")}</p>}
        {runs.map(r=><button key={r.id} className="disc-run" disabled={busy} onClick={()=>void open(r.id)}>
          <span>{r.basket.map(x=>x.toUpperCase()).join(" · ")}
            <small>{dt(r.created_at)} · {r.selected?label(r.selected):"No qualifying model"}</small></span>
          <RefreshCw size={14}/>
        </button>)}
      </section>
      <div className="pd-results">
        {!selected?<section className="disc-card pd-empty">
          <BarChart3 size={34}/><h3>{t("No portfolio study selected")}</h3>
          <p>{t("Compare historical portfolio allocations on your private Windows backend, or reopen saved studies.")}</p>
        </section>:<>
          <section className="disc-card">
            <h3>{t("Basket research summary")}</h3>
            <div className="pd-kpis">
              <div><small>{t("Instruments")}</small><strong>{selected.basket.length}</strong></div>
              <div><small>{t("Observed sessions")}</small><strong>{selected.sessions}</strong></div>
              <div><small>{t("Models")}</small><strong>{selected.candidate_count}</strong></div>
              <div><small>{t("Qualified")}</small><strong>{selected.eligible_count}</strong></div>
            </div>
            <p className="disc-muted">{selected.first_session} to {selected.last_session} · {selected.train_sessions} training / {selected.validation_sessions} validation / {selected.test_sessions} held out</p>
            <div className="pd-groups">{Object.entries(selected.groups).map(([g,assets])=>
              <span key={g}><b>{t(g.replaceAll("_"," "))}</b> {assets.map(x=>x.toUpperCase()).join(", ")}</span>)}</div>
            <p className="disc-muted">{selected.qualification_note}</p>
          </section>
          <section className="disc-card">
            <h3>{t("Model comparison, validation only")}</h3>
            <div className="ops-table-wrap"><table><thead><tr>
              <th>{t("Model")}</th><th>{t("Net return")}</th><th>{t("Drawdown")}</th>
              <th>{t("Sharpe")}</th><th>{t("Turnover")}</th><th>{t("Score")}</th><th>{t("Qualified")}</th>
            </tr></thead><tbody>
            {selected.candidates.map(c=><tr key={c.model} className={c.model===chosen?.model?"pd-winner":undefined}>
              <td><strong>{t(label(c.model))}</strong><small>{t(descriptions[c.model]??"")}</small></td>
              <td>{pct(c.validation.return_pct)}</td>
              <td>{pct(c.validation.max_drawdown_pct)}</td>
              <td>{num(c.validation.sharpe)}</td>
              <td>{pct(c.validation.turnover_pct)}</td>
              <td>{c.score.toFixed(2)}</td>
              <td>{c.qualified?t("Yes"):t("No")}</td>
            </tr>)}</tbody></table></div>
            <p className="disc-muted">{t("Ranking uses validation net return, drawdown and turnover. Test results are not used for selection.")}</p>
          </section>
          {chosen&&metrics?<section className="disc-card">
            <h3>{t("Selected historical portfolio")} · {t(label(chosen.model))}</h3>
            <p className="disc-muted">{chosen.warning}</p>
            <div className="pd-tabs" role="tablist" aria-label={t("Portfolio study views")}>
              {(["performance","allocation","executions"] as DetailTab[]).map(view=>
                <button key={view} type="button" role="tab"
                  aria-selected={tab===view} className={tab===view?"pd-active":""}
                  onClick={()=>setTab(view)}>{t(view==="performance"?"Performance":view==="allocation"?"Allocation and correlations":"Executions")}</button>)}
            </div>
            {tab==="performance"&&<>
              <h4>{t("Held-out portfolio test versus equal-weight benchmark")}</h4>
              <div className="pd-kpis">
                <div><small>{t("Selected return")}</small><strong>{pct(metrics.return_pct)}</strong></div>
                <div><small>{t("Equal weight return")}</small><strong>{pct(chosen.held_out_equal_weight_benchmark.return_pct)}</strong></div>
                <div><small>{t("Max drawdown")}</small><strong>{pct(metrics.max_drawdown_pct)}</strong></div>
                <div><small>{t("Sharpe")}</small><strong>{num(metrics.sharpe)}</strong></div>
                <div><small>{t("Portfolio fees")}</small><strong>{dollars(metrics.fees)}</strong></div>
                <div><small>{t("Average invested")}</small><strong>{pct(metrics.average_invested_pct)}</strong></div>
              </div>
              <Curves chosen={metrics.equity_curve} benchmark={chosen.held_out_equal_weight_benchmark.equity_curve}/>
              <div className="pd-comparison"><span><b>{t("Training return")}</b> {pct(chosen.train.return_pct)}</span>
                <span><b>{t("Validation return")}</b> {pct(chosen.validation.return_pct)}</span>
                <span><b>{t("Held-out return")}</b> {pct(metrics.return_pct)}</span></div>
            </>}
            {tab==="allocation"&&<>
              <h4>{t("Ending allocation on held-out sample")}</h4>
              <div className="pd-weights">
                {Object.entries(metrics.final_weights_pct).sort((a,b)=>b[1]-a[1]).map(([symbol,value])=>
                  <div key={symbol}><span>{symbol.toUpperCase()}</span><div className="pd-track"><i style={{width:pct(Math.max(0,Math.min(100,value)))}}/></div><b>{pct(value)}</b></div>)}
                <div><span>{t("Cash")}</span><div className="pd-track"><i style={{width:pct(Math.max(0,metrics.cash_pct))}}/></div>
                  <b>{pct(metrics.cash_pct)}</b></div>
              </div>
              <h4>{t("Historical correlation matrix, training and validation only")}</h4>
              <div className="ops-table-wrap"><table className="pd-matrix"><thead><tr><th/>
                {selected.basket.map(s=><th key={s}>{s.toUpperCase()}</th>)}</tr></thead><tbody>
                  {selected.basket.map(s=><tr key={s}><th>{s.toUpperCase()}</th>
                    {selected.basket.map(peer=><td key={peer}>
                      {selected.correlation_matrix[s]?.[peer]===null?"N/A":selected.correlation_matrix[s]?.[peer]?.toFixed(2)??"N/A"}
                    </td>)}</tr>)}</tbody></table></div>
              <p className="disc-muted">{t("Correlations vary over time. Diversification does not eliminate losses.")}</p>
              <h4>{t("Recent rebalance snapshots")}</h4>
              <div className="ops-table-wrap"><table><thead><tr><th>{t("Session")}</th><th>{t("Cash")}</th><th>{t("Observed weights after open")}</th></tr></thead>
                <tbody>{metrics.rebalances.slice(-12).reverse().map(x=><tr key={x.time}>
                  <td>{dt(x.time)}</td><td>{pct(x.cash_pct)}</td>
                  <td>{Object.entries(x.weights).filter(([,w])=>w>.001).map(([s,w])=>s.toUpperCase()+" "+pct(w*100)).join(" · ")||"Cash"}</td>
                </tr>)}</tbody></table></div>
            </>}
            {tab==="executions"&&<>
              <div className="pd-kpis">
                <div><small>{t("Trades")}</small><strong>{metrics.trades}</strong></div>
                <div><small>{t("Turnover")}</small><strong>{pct(metrics.turnover_pct)}</strong></div>
                <div><small>{t("Estimated fees")}</small><strong>{dollars(metrics.fees)}</strong></div>
                <div><small>{t("Ending portfolio value")}</small><strong>{dollars(metrics.ending_equity)}</strong></div>
              </div>
              <div className="ops-table-wrap"><table><thead><tr>
                <th>{t("Date")}</th><th>{t("Asset")}</th><th>{t("Side")}</th><th>{t("Quantity")}</th><th>{t("Fill price")}</th><th>{t("Notional")}</th><th>{t("Fee")}</th>
              </tr></thead><tbody>
              {metrics.executions.slice(-60).reverse().map((trade,i)=><tr key={trade.time+"-"+trade.symbol+"-"+trade.side+"-"+i}>
                <td>{dt(trade.time)}</td><td>{trade.symbol.toUpperCase()}</td>
                <td>{trade.side.toUpperCase()}</td><td>{trade.quantity.toLocaleString()}</td>
                <td>{dollars(trade.price)}</td><td>{dollars(trade.notional)}</td>
                <td>{dollars(trade.fee)}</td>
              </tr>)}</tbody></table></div>
              <p className="disc-muted">{t("Simulated fills, not real broker transactions. No automatic deployment or broker order submission.")}</p>
            </>}
          </section>:<section className="disc-card">
            <h3>{t("No portfolio model qualified")}</h3><p className="disc-muted">{selected.qualification_note}</p>
          </section>}
          <section className="disc-card"><h3>{t("Method and limitations")}</h3>
            <p className="disc-muted">{selected.assumptions}</p>
            <p className="disc-muted">{t("Private research remains on your Windows PC. These models are not executable portfolio DSL rules; independent paper evaluation is required before deployment.")}</p>
          </section>
        </>}
      </div>
    </div>
  </div>;
}
