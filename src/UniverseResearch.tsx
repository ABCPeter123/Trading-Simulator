import {useCallback,useEffect,useState} from "react";
import {request} from "./api";
import {importTournamentRank,createTournamentReplay} from "./tournamentApi";
import {useI18n} from "./i18n";
import "./universeResearch.css";

type Metric={return_pct:number;max_drawdown_pct:number;trades:number;fees:number;turnover_pct:number};
type Scenario={name:string;horizon_sessions:number;p05_return_pct:number;median_return_pct:number;p95_return_pct:number;median_max_drawdown_pct:number;
  daily?:{session:number;p05_return_pct:number;median_return_pct:number;p95_return_pct:number}[]};
type Winner={rank:number;basket_type:string;symbols:string[];model:string;validation_score:number;training:Metric;
  validation:Metric;held_out:Metric;delayed_execution_stress:Metric;restricted_research:boolean;
  short_proxy_research:boolean;hypothetical_scenarios:{paths:Scenario[]};execution_model:string};
type Outcome={universe_count:number;eligible_count:number;excluded_count:number;qualified_candidates:number;
  basket_count:number;candidates_evaluated:number;top10:Winner[];limitations:string[];
  selection_method:string;execution_assumptions:Record<string,string|number>};
type Job={id:string;status:"queued"|"running"|"completed"|"failed"|"cancelled";created_at:string;
  progress:number;stage:string;scanned:number;eligible:number;error_code:string|null;
  params:{scope:string;delay_sessions:1|2;max_drawdown_pct:number;max_position_pct:number};result:Outcome|null};
import {validatedPercent} from "./validatedPercent";

const pct=(x:number)=>Number.isFinite(x)?x.toFixed(2)+"%":"N/A";
const label=(x:string)=>x.replaceAll("_"," ").replace(/\b\w/g,c=>c.toUpperCase());
export default function UniverseResearch({onOpenDiscovery,onOpenSimulation,onOpenLive}:{
  onOpenDiscovery:()=>void;onOpenSimulation:(runId:string)=>void;onOpenLive:(strategyId:string)=>void;
}){
  const {t}=useI18n();
  const [scope,setScope]=useState<"all"|"etfs"|"stocks">("all");
  const [delay,setDelay]=useState<1|2>(1);
  const [drawdown,setDrawdown]=useState("30");
  const [weight,setWeight]=useState("35");
  const [jobs,setJobs]=useState<Job[]>([]);
  const [active,setActive]=useState<Job|null>(null);
  const [pick,setPick]=useState(0);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const refresh=useCallback(async()=>{
    const rows=await request<Job[]>("/live/research/universe/jobs");
    if(!Array.isArray(rows))throw new Error("Research queue returned an invalid response.");
    setJobs(rows);
    return rows;
  },[]);
  useEffect(()=>{
    let alive=true;
    void refresh().then(rows=>{
      if(!alive||!rows.length)return;
      void request<Job>("/live/research/universe/jobs/"+encodeURIComponent(rows[0].id))
        .then(j=>{if(alive)setActive(j);}).catch(()=>{});
    }).catch(e=>{if(alive)setError(String(e));});
    return()=>{alive=false;};
  },[refresh]);
  useEffect(()=>{
    let alive=true;
    const timer=window.setInterval(()=>{
      void refresh().then(rows=>{
        const id=active?.id??rows[0]?.id;
        if(!alive||!id)return;
        void request<Job>("/live/research/universe/jobs/"+encodeURIComponent(id))
          .then(j=>{if(alive)setActive(j);}).catch(()=>{});
      }).catch(()=>{});
    },5000);
    return()=>{alive=false;window.clearInterval(timer);};
  },[refresh,active?.id]);
  async function run(){
    setBusy(true);setError("");
    try{
      const max_drawdown_pct=validatedPercent(drawdown,"Maximum validation drawdown",5,60);
      const max_position_pct=validatedPercent(weight,"Maximum position weight",10,50);
      const job=await request<Job>("/live/research/universe/jobs",{method:"POST",
        body:JSON.stringify({scope,delay_sessions:delay,
          max_drawdown_pct,max_position_pct})});
      setActive(job);setPick(0);await refresh();
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function open(id:string){
    setBusy(true);setError("");
    try{
      const job=await request<Job>("/live/research/universe/jobs/"+encodeURIComponent(id));
      setActive(job);setPick(0);
    }catch(e){setError(String(e));}
    finally{setBusy(false);}
  }
  async function cancel(){
    if(!active)return;
    try{
      await request("/live/research/universe/jobs/"+encodeURIComponent(active.id)+"/cancel",{method:"POST"});
      await open(active.id);
    }catch(e){setError(String(e));}
  }
  async function promote(destination:"simulation"|"live"){
    if(!active||!chosen)return;
    setBusy(true);setError("");setNotice("");
    try{
      const version=await importTournamentRank(active.id,chosen.rank);
      if(destination==="simulation"){
        const replay=await createTournamentReplay(version.id);
        onOpenSimulation(replay.id);
      }else{
        onOpenLive(version.id);
      }
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function importAll(){
    if(!active||!result?.top10.length)return;
    setBusy(true);setError("");setNotice("");
    try{
      for(const winner of result.top10){
        await importTournamentRank(active.id,winner.rank);
      }
      setNotice(t("All ranked portfolio models saved privately. Open the Live Engine to select a paper strategy."));
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  const result=active?.result;
  const chosen=result?.top10[pick];
  return <main className="ur-shell">
    <header className="ur-header"><div>
      <p className="ur-kicker">{t("PRIVATE QUANTITATIVE RESEARCH")}</p>
      <h1>{t("Strategy Tournament")}</h1>
      <p>{t("Scan actual instrument history, rank the top ten portfolio strategies, and inspect delay and scenario stress. Nothing trades automatically.")}</p>
    </div></header>
    <div className="ur-steps">{[
      ["1",t("Collect history"),t("Screen actual daily OHLCV, exclude unavailable assets.")],
      ["2",t("Compare methods"),t("Try diversified baskets and five cash-backed portfolio models.")],
      ["3",t("Rank validation"),t("The held-out final 20% never determines the ranking.")],
      ["4",t("Stress test"),t("Inspect execution costs, extra delay and hypothetical paths.")],
    ].map(([n,title,desc])=><article key={n}><b>{n}. {title}</b><p>{desc}</p></article>)}</div>
    {error&&<p className="ops-error" role="alert">{error}</p>}
    {notice&&<p className="ops-message" role="status">{notice}</p>}
    <div className="ur-columns">
      <section className="ur-panel"><h2>{t("Configure tournament")}</h2>
        <label>{t("Universe")}
          <select value={scope} onChange={e=>setScope(e.target.value as typeof scope)}>
            <option value="all">{t("All stocks and ETFs")}</option>
            <option value="etfs">{t("ETFs only")}</option>
            <option value="stocks">{t("Stocks only")}</option>
          </select></label>
        <label>{t("Signal execution delay")}
          <select value={delay} onChange={e=>setDelay(Number(e.target.value) as 1|2)}>
            <option value={1}>{t("Next session open")}</option>
            <option value={2}>{t("Second session open")}</option>
          </select></label>
        <label>{t("Maximum validation drawdown (%)")}
          <input type="number" min="5" max="60" value={drawdown} onChange={e=>setDrawdown(e.target.value)}/></label>
        <label>{t("Maximum position weight (%)")}
          <input type="number" min="10" max="50" value={weight} onChange={e=>setWeight(e.target.value)}/></label>
        <button className="ur-primary" disabled={busy} onClick={()=>void run()}>{t("Run universe-wide scan")}</button>
        <p>{t("The laptop research worker performs all calculations. Historical data availability determines how many symbols qualify.")}</p>
        <button className="ur-secondary" onClick={onOpenDiscovery}>{t("Open individual optimizers")}</button>
        <h3>{t("Previous scans")}</h3>
        {jobs.length===0?<p>{t("No scans recorded.")}</p>:jobs.map(job=>
          <button type="button" disabled={busy} key={job.id} className="ur-job"
            onClick={()=>void open(job.id)}>
            <strong>{new Date(job.created_at).toLocaleString()}</strong>
            <span>{t(job.status)} · {job.eligible}/{job.scanned}</span>
          </button>)}
      </section>
      <section className="ur-panel ur-results">
        {!active?<div><h2>{t("Start your first scan")}</h2>
          <p>{t("Use real backfilled data. Scans with insufficient historical coverage may produce fewer than ten results.")}</p>
        </div>:<>
          <h2>{t("Research progress")}: {t(active.status)}</h2>
          <p>{active.stage} · {active.progress}% · {active.eligible}/{active.scanned} {t("eligible")}</p>
          {(active.status==="queued"||active.status==="running")&&<>
            <div className="ur-progress" role="progressbar" aria-valuenow={active.progress}
              aria-valuemin={0} aria-valuemax={100}><i style={{width:active.progress+"%"}}/></div>
            <button className="ur-secondary" onClick={()=>void cancel()}>{t("Cancel scan")}</button>
          </>}
          {active.error_code&&<p role="alert">{active.error_code}</p>}
          {result&&<>
            <div className="ur-kpis">
              {[[t("Catalog"),result.universe_count],[t("Eligible"),result.eligible_count],
                [t("Evaluated"),result.candidates_evaluated],[t("Qualified"),result.qualified_candidates],
                [t("Ranked"),result.top10.length]].map(([name,n])=>
                <div key={String(name)}><small>{name}</small><strong>{n}</strong></div>)}
            </div>
            <p>{t("Ranked using historical validation only. Held-out tests and simulated futures do not influence selection.")}</p>
            <h2>{t("Top 10 research strategies")}</h2>
            <button type="button" className="ur-secondary" disabled={busy||!result.top10.length}
              onClick={()=>void importAll()}>{t("Save all top 10 as executable models")}</button>
            {result.top10.length===0?<p>{t("No qualifying candidates. Inspect missing history or relax the validation constraints.")}</p>:
            <div className="ur-scroll"><table><thead><tr><th>{t("Rank")}</th>
              <th>{t("Basket / Model")}</th><th>{t("Validation")}</th>
              <th>{t("Drawdown")}</th><th>{t("Held-out")}</th><th>{t("Score")}</th>
            </tr></thead><tbody>{result.top10.map((row,i)=><tr key={row.rank} className={i===pick?"ur-active":""}>
              <td><button className="ur-link" onClick={()=>setPick(i)}>#{row.rank}</button></td>
              <td><button className="ur-link" onClick={()=>setPick(i)}>{label(row.basket_type)} · {label(row.model)}</button>
                <small>{row.symbols.join(", ").toUpperCase()}</small></td>
              <td>{pct(row.validation.return_pct)}</td><td>{pct(row.validation.max_drawdown_pct)}</td>
              <td>{pct(row.held_out.return_pct)}</td><td>{row.validation_score.toFixed(2)}</td>
            </tr>)}</tbody></table></div>}
            {chosen&&<article className="ur-detail">
              <h3>#{chosen.rank} {label(chosen.basket_type)} · {label(chosen.model)}</h3>
              <p>{chosen.symbols.map(x=>x.toUpperCase()).join(" · ")}</p>
              <p>{t("Executable model")}: {label(chosen.model)} · {active?.params.max_position_pct}% {t("Maximum position weight (%)")} ·
                {t("Every 21 common sessions")} · {active?.params.delay_sessions} {t("session execution delay")}</p>
              <div className="ur-actions">
                <button type="button" className="ur-primary" disabled={busy}
                  onClick={()=>void promote("simulation")}>{t("Load this strategy into simulation")}</button>
                <button type="button" className="ur-secondary" disabled={busy}
                  onClick={()=>void promote("live")}>{t("Open in Live Engine (paper first)")}</button>
              </div>
              <p>{t("Simulation uses the selected model, not a substitute SMA script. Live Engine imports the same version for manual-review paper signals. Eligible USD stocks and ETFs only; leveraged or inverse research stays simulation-only.")}</p>
              <div className="ur-kpis">
                {[[t("Training return"),pct(chosen.training.return_pct)],
                  [t("Validation return"),pct(chosen.validation.return_pct)],
                  [t("Held-out return"),pct(chosen.held_out.return_pct)],
                  [t("Held-out drawdown"),pct(chosen.held_out.max_drawdown_pct)],
                  [t("Slower fill stress"),pct(chosen.delayed_execution_stress.return_pct)],
                  [t("Simulated costs"),chosen.held_out.fees.toFixed(2)]].map(([name,value])=>
                  <div key={name}><small>{name}</small><strong>{value}</strong></div>)}
              </div>
              {(chosen.restricted_research||chosen.short_proxy_research)&&
                <p className="ur-warning">{t("Leveraged/inverse ETF exposure is research-only, not a share short or approved broker order.")}</p>}
              <p>{chosen.execution_model}</p>
              <h4>{t("Hypothetical 30-session scenarios")}</h4>
              <div className="ur-scroll"><table><thead><tr><th>{t("Scenario")}</th>
                <th>5%</th><th>{t("Median")}</th><th>95%</th><th>{t("Median drawdown")}</th>
              </tr></thead><tbody>{chosen.hypothetical_scenarios.paths.map(row=><tr key={row.name}>
                <td>{label(row.name)}</td><td>{pct(row.p05_return_pct)}</td><td>{pct(row.median_return_pct)}</td>
                <td>{pct(row.p95_return_pct)}</td><td>{pct(row.median_max_drawdown_pct)}</td>
              </tr>)}</tbody></table></div>
              <h4>{t("Daily scenario trajectory")}</h4>
              {chosen.hypothetical_scenarios.paths.filter(x=>x.daily?.length).map(path=>
                <details key={path.name}><summary>{label(path.name)} · {t("Day-by-day percentile bands")}</summary>
                  <div className="ur-scroll"><table><thead><tr>
                    <th>{t("Trading session")}</th><th>{t("Downside 5%")}</th>
                    <th>{t("Median")}</th><th>{t("Upside 95%")}</th>
                  </tr></thead><tbody>
                    {(path.daily??[]).map(point=><tr key={point.session}>
                      <td>{point.session}</td><td>{pct(point.p05_return_pct)}</td>
                      <td>{pct(point.median_return_pct)}</td><td>{pct(point.p95_return_pct)}</td>
                    </tr>)}
                  </tbody></table></div>
                </details>)}
              <p>{t("Scenario paths are hypothetical resamples, not forecasts or calibrated probabilities.")}</p>
            </article>}
            <details><summary>{t("Cost model and limitations")}</summary>
              <p>{result.selection_method}</p>
              <p>{t("FX conversion assumption")}: {Number(result.execution_assumptions.fx_conversion_bps)/100}% ·
                {t("Slippage")}: {result.execution_assumptions.slippage_bps} bps ·
                {t("Commission")}: {result.execution_assumptions.commission_usd} USD</p>
              <p>{result.excluded_count} {t("excluded symbols")}</p>
              {result.limitations.map((line,i)=><p key={i}>{line}</p>)}
            </details>
          </>}
        </>}
      </section>
    </div>
  </main>;
}
