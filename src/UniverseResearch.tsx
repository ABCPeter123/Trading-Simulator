import {useCallback,useEffect,useState} from "react";
import {request} from "./api";
import {importTournamentRank,createTournamentReplay} from "./tournamentApi";
import TournamentStrategyInspector from "./TournamentStrategyInspector";
import {useI18n} from "./i18n";
import "./universeResearch.css";

type Metric={return_pct:number;max_drawdown_pct:number;trades:number;fees:number;turnover_pct:number;
  sharpe?:number|null;sortino?:number|null;annualized_volatility_pct?:number|null;
  peak_gross_leverage?:number;margin_interest?:number;short_borrow_cost?:number;
  margin_calls?:number;short_executions?:number;average_gross_exposure_pct?:number};
type Scenario={name:string;horizon_sessions:number;p05_return_pct:number;median_return_pct:number;p95_return_pct:number;median_max_drawdown_pct:number;
  daily?:{session:number;p05_return_pct:number;median_return_pct:number;p95_return_pct:number}[]};
type RegimeMetrics={samples:number;worst_regime_return_pct:number;
  regimes:Record<string,{observations:number;return_pct:number;positive_day_pct:number;worst_day_pct:number}>};
type ExecutionSample={time:number;symbol:string;side:string;quantity:number;price:number;fee:number;notional:number};
type Winner={rank:number;basket_type:string;symbols:string[];model:string;validation_score:number;training:Metric;
  validation:Metric;held_out:Metric;delayed_execution_stress:Metric;restricted_research:boolean;
  short_proxy_research:boolean;research_only?:boolean;
  validation_regimes?:RegimeMetrics;held_out_regimes?:RegimeMetrics;
  held_out_execution_sample?:ExecutionSample[];
  coverage?:{first_session:string;last_session:string;common_sessions:number};
  hypothetical_scenarios:{paths:Scenario[]};execution_model:string;scenario_calibration?:string};
type Outcome={universe_count:number;eligible_count:number;excluded_count:number;qualified_candidates:number;
  basket_count:number;candidates_evaluated:number;top10:Winner[];limitations:string[];
  selection_method:string;execution_assumptions:Record<string,string|number>;
  candidate_model_counts?:Record<string,number>;
  historical_coverage?:{universe_earliest_session:string|null;
    universe_latest_session:string|null;method:string};
  shortlist_is_global_top_ten?:boolean};
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
            <p>{result.selection_method}</p>
            {result.historical_coverage&&<p>{t("Available historical coverage")}: {
              result.historical_coverage.universe_earliest_session??t("Unknown")} · {
              result.historical_coverage.universe_latest_session??t("Unknown")}.
              {t("Each portfolio uses only dates shared by all of its instruments.")}</p>}
            {result.candidate_model_counts&&<details><summary>{t("Models evaluated by family")}</summary>
              <div className="ur-kpis">{Object.entries(result.candidate_model_counts).map(([name,count])=>
                <div key={name}><small>{label(name)}</small><strong>{count}</strong></div>)}</div>
            </details>}
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
                <small>{row.symbols.join(", ").toUpperCase()}</small>
                {row.research_only&&<small>{t("Synthetic short / margin research only")}</small>}</td>
              <td>{pct(row.validation.return_pct)}</td><td>{pct(row.validation.max_drawdown_pct)}</td>
              <td>{pct(row.held_out.return_pct)}</td><td>{row.validation_score.toFixed(2)}</td>
            </tr>)}</tbody></table></div>}
            {chosen&&<article className="ur-detail">
              <h3>#{chosen.rank} {label(chosen.basket_type)} · {label(chosen.model)}</h3>
              <p>{chosen.symbols.map(x=>x.toUpperCase()).join(" · ")}</p>
              <TournamentStrategyInspector key={`${active.id}-${chosen.rank}`} spec={{
                version:chosen.model==="leveraged_trend"||chosen.model==="long_short_momentum"||chosen.model==="market_neutral"||chosen.model==="defensive_rotation"||chosen.model==="diversified_risk_parity"||chosen.model==="equity_hedge"?2:1,model:chosen.model,symbols:chosen.symbols,
                max_position_pct:active.params.max_position_pct,
                delay_sessions:active.params.delay_sessions,rebalance_sessions:21,
                restricted_research:chosen.restricted_research,
                short_proxy_research:chosen.short_proxy_research,
                research_only:chosen.research_only,
              }} costs={{
                commission_usd:Number(result.execution_assumptions.commission_usd),
                slippage_bps:Number(result.execution_assumptions.slippage_bps),
                fx_conversion_bps:Number(result.execution_assumptions.fx_conversion_bps),
                base_currency:String(result.execution_assumptions.base_currency),
              }} />
              <p>{t("Executable model")}: {label(chosen.model)} · {active?.params.max_position_pct}% {t("Maximum position weight (%)")} ·
                {t("Every 21 common sessions")} · {active?.params.delay_sessions} {t("session execution delay")}</p>
              <div className="ur-actions">
                <button type="button" className="ur-primary" disabled={busy||chosen.research_only}
                  onClick={()=>void promote("simulation")}>{t("Load this strategy into simulation")}</button>
                <button type="button" className="ur-secondary" disabled={busy||chosen.research_only}
                  onClick={()=>void promote("live")}>{t("Open in Live Engine (paper first)")}</button>
              </div>
              <p>{chosen.research_only?
                t("Real share shorting and margin borrowing are evaluated only in the historical research model. This strategy cannot be loaded into the cash simulator or live engine. The audited historical test and trades remain available here."):
                t("Supported cash-funded models can be loaded into simulation and paper monitoring. Leveraged and inverse ETFs are separately restricted for live monitoring.")}</p>
              <div className="ur-kpis">
                {[[t("Training return"),pct(chosen.training.return_pct)],
                  [t("Validation return"),pct(chosen.validation.return_pct)],
                  [t("Held-out return"),pct(chosen.held_out.return_pct)],
                  [t("Held-out drawdown"),pct(chosen.held_out.max_drawdown_pct)],
                  [t("Slower fill stress"),pct(chosen.delayed_execution_stress.return_pct)],
                  [t("Simulated costs"),chosen.held_out.fees.toFixed(2)],
                  [t("Validation Sharpe"),chosen.validation.sharpe?.toFixed(2)??"N/A"],
                  [t("Validation Sortino"),chosen.validation.sortino?.toFixed(2)??"N/A"],
                  [t("Peak gross leverage"),chosen.held_out.peak_gross_leverage?.toFixed(2)??"N/A"],
                  [t("Margin interest"),chosen.held_out.margin_interest?.toFixed(2)??"N/A"],
                  [t("Short borrow costs"),chosen.held_out.short_borrow_cost?.toFixed(2)??"N/A"],
                  [t("Margin calls"),chosen.held_out.margin_calls??0]].map(([name,value])=>
                  <div key={name}><small>{name}</small><strong>{value}</strong></div>)}
              </div>
              {(chosen.restricted_research||chosen.short_proxy_research)&&
                <p className="ur-warning">{t("Leveraged/inverse ETF exposure is research-only, not a share short or approved broker order.")}</p>}
              {chosen.coverage&&<p>{t("Actual common history")}: {chosen.coverage.first_session}
                {" → "}{chosen.coverage.last_session} · {chosen.coverage.common_sessions} {t("common sessions")}.</p>}
              {chosen.validation_regimes&&<details open><summary>{t("Historical validation performance by market regime")}</summary>
                <div className="ur-scroll"><table><thead><tr>
                  <th>{t("Regime")}</th><th>{t("Observed sessions")}</th>
                  <th>{t("Compounded return")}</th><th>{t("Positive days")}</th><th>{t("Worst day")}</th>
                </tr></thead><tbody>{Object.entries(chosen.validation_regimes.regimes).map(([regime,x])=>
                  <tr key={regime}><td>{label(regime)}</td><td>{x.observations}</td>
                    <td>{pct(x.return_pct)}</td><td>{pct(x.positive_day_pct)}</td><td>{pct(x.worst_day_pct)}</td></tr>)}
                </tbody></table></div></details>}
              {(chosen.held_out_execution_sample?.length??0)>0&&<details>
                <summary>{t("Historical test trade executions")}</summary>
                <div className="ur-scroll"><table><thead><tr><th>{t("Time")}</th><th>{t("Asset")}</th>
                  <th>{t("Side")}</th><th>{t("Quantity")}</th><th>{t("Price")}</th><th>{t("Fee")}</th></tr>
                </thead><tbody>{chosen.held_out_execution_sample?.map((x,i)=><tr key={i}>
                  <td>{new Date(x.time*1000).toLocaleDateString()}</td>
                  <td>{x.symbol.toUpperCase()}</td><td>{label(x.side)}</td><td>{x.quantity}</td>
                  <td>{x.price.toFixed(2)}</td><td>{x.fee.toFixed(2)}</td></tr>)}</tbody></table></div>
              </details>}
              <p>{chosen.execution_model}</p>
              {chosen.scenario_calibration&&<p>{chosen.scenario_calibration}</p>}
              <h4>{t("Hypothetical 10-120 session scenarios")}</h4>
              <div className="ur-scroll"><table><thead><tr><th>{t("Scenario")}</th>
                <th>{t("Sessions")}</th><th>5%</th><th>{t("Median")}</th><th>95%</th><th>{t("Median drawdown")}</th>
              </tr></thead><tbody>{chosen.hypothetical_scenarios.paths.map(row=><tr key={`${row.name}-${row.horizon_sessions}`}>
                <td>{label(row.name)}</td><td>{row.horizon_sessions}</td><td>{pct(row.p05_return_pct)}</td><td>{pct(row.median_return_pct)}</td>
                <td>{pct(row.p95_return_pct)}</td><td>{pct(row.median_max_drawdown_pct)}</td>
              </tr>)}</tbody></table></div>
              <h4>{t("Daily scenario trajectory")}</h4>
              {chosen.hypothetical_scenarios.paths.filter(x=>x.daily?.length).map(path=>
                <details key={`${path.name}-${path.horizon_sessions}`}><summary>{label(path.name)} · {path.horizon_sessions} {t("Sessions")} · {t("Day-by-day percentile bands")}</summary>
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
