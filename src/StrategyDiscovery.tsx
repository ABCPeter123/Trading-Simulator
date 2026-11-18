import {useCallback,useEffect,useState} from "react";
import {Activity,BarChart3,BookOpen,CheckCircle2,RefreshCw,ShieldCheck} from "lucide-react";
import {useI18n} from "./i18n";
import {request} from "./api";
import "./strategyDiscovery.css";
import PortfolioDiscovery from "./PortfolioDiscovery";

interface CurvePoint {time:number;value:number}
interface Metric {
  return_pct:number;max_drawdown_pct:number;annualized_volatility_pct:number|null;
  sharpe:number|null;sortino:number|null;trades:number;equity_curve:CurvePoint[];
}
interface Candidate {
  fast:number;slow:number;score:number;qualified:boolean;
  train:Omit<Metric,"equity_curve">;validation:Omit<Metric,"equity_curve">;
}
interface Optimization {
  id:string;asset_id:string;created_at:string;data_source:string;bars_count:number;
  train_bars:number;validation_bars:number;test_bars:number;
  max_drawdown_limit_pct:number;allocation_pct:number;candidate_count:number;
  eligible_count:number;candidates:Candidate[];
  selection_method:string;assumptions:string;test_used_for_selection:boolean;
  selected:null|{fast:number;slow:number;strategy_code:string;train:Metric;
    validation:Metric;held_out_test:Metric;warning:string};
  qualification_note:string;
}
interface SavedResearch {id:string;asset_id:string;created_at:string;candidate_count:number;
  eligible_count:number;selected:null|{fast:number;slow:number};}
const percent=(value:number)=>value.toFixed(2)+"%";
const numeric=(value:number|null)=>value===null?"N/A":Number(value).toFixed(2);
const iso=(x:string)=>new Date(x).toLocaleString();

function EquityChart({points}:{points:CurvePoint[]}){
  if(points.length<2)return <div className="disc-muted">No recorded equity points</div>;
  const values=points.map(x=>x.value);
  const lo=Math.min(...values)*.997,hi=Math.max(...values)*1.003;
  const height=Math.max(hi-lo,1e-7);
  // The entire period is drawn. There is no random display cutoff or
  // hidden last-N-bars sampling.
  const coordinates=points.map((p,i)=>{
    const x=40+920*i/(points.length-1);
    const y=180-150*(p.value-lo)/height;
    return x.toFixed(2)+","+y.toFixed(2);
  }).join(" ");
  return <svg viewBox="0 0 1000 220" className="disc-equity" role="img"
    aria-label={"Full "+points.length+" point equity curve"}>
    <line x1="40" y1="180" x2="960" y2="180" stroke="#39495a"/>
    <line x1="40" y1="30" x2="40" y2="180" stroke="#39495a"/>
    <polyline points={coordinates} fill="none" stroke="#60d0ad" strokeWidth="2.6"
      strokeLinejoin="round" strokeLinecap="round"/>
    <text x="44" y="19" fontSize="17" fill="#b9cada">{hi.toFixed(0)}</text>
    <text x="44" y="202" fontSize="17" fill="#9bafbd">{lo.toFixed(0)}</text>
    <text x="820" y="209" fontSize="14" fill="#90a3b8">{points.length} bars</text>
  </svg>;
}
function Stats({title,values}:{title:string;values:Metric}){
  const {t}=useI18n();
  return <section className="disc-stat">
    <h3>{t(title)}</h3>
    <div className="disc-grid-two">
      <div><small>{t("Net return")}</small><strong>{percent(values.return_pct)}</strong></div>
      <div><small>{t("Max drawdown")}</small><strong>{percent(values.max_drawdown_pct)}</strong></div>
      <div><small>{t("Sharpe (historical)")}</small><strong>{numeric(values.sharpe)}</strong></div>
      <div><small>{t("Executed trades")}</small><strong>{values.trades}</strong></div>
    </div>
    <EquityChart points={values.equity_curve}/>
  </section>;
}

import {validatedPercent} from "./validatedPercent";

function SingleAssetDiscovery(){
  const {t}=useI18n();
  const [asset,setAsset]=useState("spy");
  const [drawdown,setDrawdown]=useState("15");
  const [allocation,setAllocation]=useState("20");
  const [runs,setRuns]=useState<SavedResearch[]>([]);
  const [selected,setSelected]=useState<Optimization|null>(null);
  const [name,setName]=useState("");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const refresh=useCallback(async()=>{
    setRuns(await request<SavedResearch[]>("/live/research/runs"));
  },[]);
  useEffect(()=>{void refresh().catch(e=>setError(String(e)));},[refresh]);
  async function optimize(){
    setBusy(true);setError("");setMessage("");
    try{
      const result=await request<Optimization>("/live/research/optimize",{
        method:"POST",body:JSON.stringify({
          asset_id:asset.trim().toLowerCase(),
          max_drawdown_pct:validatedPercent(drawdown,"Maximum validation drawdown",1,50),
          allocation_pct:validatedPercent(allocation,"Position allocation",1,25),
        }),
      });
      setSelected(result);setName("");await refresh();
      setMessage(t("Research completed and saved privately. Review validation and held-out test separately."));
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function open(id:string){
    setBusy(true);setError("");
    try{setSelected(await request<Optimization>("/live/research/runs/"+encodeURIComponent(id)));}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function save(){
    if(!selected?.selected||!name.trim())return;
    setBusy(true);setError("");setMessage("");
    try{
      await request("/live/research/runs/"+encodeURIComponent(selected.id)+"/save",{
        method:"POST",body:JSON.stringify({name:name.trim()}),
      });
      setMessage(t("Selected candidate saved to private strategy library. It is not deployed."));
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  return <main className="disc-shell">
    <header className="disc-head">
      <div><p className="disc-kicker">{t("STRATEGY DISCOVERY")}</p>
        <h1>{t("Train, validate, and stress-check candidates")}</h1>
        <p>{t("This research experiment ranks simple crossover candidates using training and validation data. The held-out test is inspected only after selection.")}</p>
      </div>
      <div className="disc-mode"><ShieldCheck size={18}/>{t("Private research only")}</div>
    </header>
    {error&&<div className="ops-error" role="alert">{error}</div>}
    {message&&<div className="ops-message" role="status">{message}</div>}
    <div className="disc-layout">
      <section className="disc-card">
        <h2><Activity size={17}/>{t("Configure a research experiment")}</h2>
        <label>{t("Stock or ETF symbol")}<input value={asset} onChange={e=>setAsset(e.target.value)}
          maxLength={30} placeholder="spy"/></label>
        <label>{t("Maximum validation drawdown (%)")}
          <input type="number" min="1" max="50" value={drawdown} onChange={e=>setDrawdown(e.target.value)}/></label>
        <label>{t("Position allocation (%)")}
          <input type="number" min="1" max="25" value={allocation} onChange={e=>setAllocation(e.target.value)}/></label>
        <button className="disc-primary" disabled={busy||!asset.trim()} onClick={()=>void optimize()}>
          <BarChart3 size={17}/>{busy?t("Analyzing..."):t("Run private optimization")}</button>
        <p className="disc-muted">{t("Training 60%, validation 20%, held-out test 20%. Models are selected without looking at the test period. Historical performance does not ensure future profits.")}</p>
        <h3>{t("Saved research experiments")}</h3>
        {!runs.length&&<p className="disc-muted">{t("No saved research runs yet.")}</p>}
        {runs.map(x=><button className="disc-run" key={x.id} disabled={busy} onClick={()=>void open(x.id)}>
          <span>{x.asset_id.toUpperCase()} · {iso(x.created_at)}<small>{x.candidate_count} {t("candidates")} · {x.eligible_count} {t("qualified")}</small></span>
          <RefreshCw size={14}/>
        </button>)}
      </section>
      <div className="disc-results">
        {!selected?<section className="disc-card disc-placeholder">
          <BookOpen size={34}/><h2>{t("No experiment selected")}</h2>
          <p>{t("Run a new study or open a previous experiment. Research results and selected rule parameters are stored on your private machine, not on Vercel or GitHub.")}</p>
        </section>:<>
          <section className="disc-card">
            <h2>{selected.asset_id.toUpperCase()} · {t("Research summary")}</h2>
            <div className="disc-summary">
              <div><small>{t("Historical candles")}</small><strong>{selected.bars_count}</strong></div>
              <div><small>{t("Candidates evaluated")}</small><strong>{selected.candidate_count}</strong></div>
              <div><small>{t("Validation qualified")}</small><strong>{selected.eligible_count}</strong></div>
              <div><small>{t("Test leakage")}</small><strong>{selected.test_used_for_selection?"ERROR":"None"}</strong></div>
            </div>
            <p className="disc-muted">{selected.data_source} · {selected.selection_method}</p>
            <p className="disc-muted">{selected.qualification_note}</p>
          </section>
          {selected.selected?<section className="disc-card">
            <h2><CheckCircle2 size={17}/>{t("Selected historical candidate")}</h2>
            <div className="disc-selected"><strong>SMA {selected.selected.fast} / {selected.selected.slow}</strong>
              <small>{t("Selected on validation only. Not deployed.")}</small></div>
            <div className="disc-periods">
              <Stats title="Training" values={selected.selected.train}/>
              <Stats title="Validation" values={selected.selected.validation}/>
              <Stats title="Held-out test" values={selected.selected.held_out_test}/>
            </div>
            <p className="disc-muted">{selected.selected.warning}</p>
            <div className="disc-save">
              <label>{t("Private strategy version name")}<input value={name} onChange={e=>setName(e.target.value)} maxLength={80}
                placeholder={t("Name this candidate before saving")}/></label>
              <button disabled={busy||!name.trim()} onClick={()=>void save()}>{t("Save to private strategy library")}</button>
            </div>
            <p className="disc-muted">{t("Saving only creates a new version. Deploy separately in the Live Strategy Machine after paper testing.")}</p>
          </section>:<section className="disc-card"><p className="disc-muted">
            {t("No candidate met the validation risk and trade activity requirements. Nothing was deployed.")}</p></section>}
          <section className="disc-card">
            <h2>{t("Candidate ranking (validation only)")}</h2>
            <div className="ops-table-wrap"><table><thead><tr><th>{t("Parameters")}</th><th>{t("Validation return")}</th>
              <th>{t("Validation max drawdown")}</th><th>{t("Trades")}</th><th>{t("Qualified")}</th><th>{t("Score")}</th></tr></thead>
              <tbody>{selected.candidates.map(x=><tr key={x.fast+"-"+x.slow}><td>{x.fast}/{x.slow}</td>
                <td>{percent(x.validation.return_pct)}</td><td>{percent(x.validation.max_drawdown_pct)}</td>
                <td>{x.validation.trades}</td><td>{x.qualified?t("Yes"):t("No")}</td><td>{numeric(x.score)}</td></tr>)}</tbody></table></div>
            <p className="disc-muted">{selected.assumptions}</p>
          </section>
        </>}
      </div>
    </div>
  </main>;
}

export default function StrategyDiscovery(){
  const {t}=useI18n();
  const [mode,setMode]=useState<"portfolio"|"legacy">("portfolio");
  return <section className="disc-workspace">
    <nav className="pd-switch" aria-label={t("Research scope")}>
      <button type="button" aria-current={mode==="portfolio"?"page":undefined}
        onClick={()=>setMode("portfolio")}>{t("Portfolio research, multi-asset")}</button>
      <button type="button" aria-current={mode==="legacy"?"page":undefined}
        onClick={()=>setMode("legacy")}>{t("Single-asset SMA, legacy")}</button>
    </nav>
    {mode==="portfolio"?<main className="disc-shell"><PortfolioDiscovery/></main>:<SingleAssetDiscovery/>}
  </section>;
}
