import {useEffect,useMemo,useState} from "react";
import {useI18n} from "./i18n";
import {submitWalkForward,getWalkForward,listWalkForward,cancelWalkForward} from "./tournamentApi";
import type {TournamentSourceSpec,WalkForwardJob,WalkForwardResult,WalkForwardSelection} from "./tournamentApi";
import "./walkForwardOptimizer.css";

const pct=(value:number|null|undefined)=>value==null||!Number.isFinite(value)?"N/A":value.toFixed(2)+"%";
const dec=(value:number|null|undefined)=>value==null||!Number.isFinite(value)?"N/A":value.toFixed(2);
const name=(value:string)=>value.replaceAll("_"," ").replace(/\b\w/g,c=>c.toUpperCase());
const money=(n:number)=>new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:0}).format(n);

function Plot({data,description}:{data:{time:number;value:number}[];description:string}){
  const path=useMemo(()=>{
    if(data.length===0)return "";
    let min=Infinity,max=-Infinity;
    for(const point of data){min=Math.min(min,point.value);max=Math.max(max,point.value);}
    const span=Math.max(max-min,1);
    const stride=Math.max(1,Math.ceil(data.length/300));
    return data.filter((_,i)=>i%stride===0||i===data.length-1).map((point,i)=>{
      const index=Math.min(data.length-1,i*stride);
      return (i===0?"M":"L")+
        (8+684*index/Math.max(1,data.length-1)).toFixed(2)+","+
        (159-144*(point.value-min)/span).toFixed(2);
    }).join(" ");
  },[data]);
  if(!data.length)return null;
  return <svg viewBox="0 0 704 174" role="img" aria-label={description} className="wfo-plot">
    <title>{description}</title>
    <path d={path} fill="none" stroke="#5cc9ae" strokeWidth="2.5"
      strokeLinejoin="round" strokeLinecap="round"/>
  </svg>;
}

function Selection({value,locale}:{value:WalkForwardSelection;locale:"en"|"zh-CN"}){
  const zh=locale==="zh-CN";
  return <span className="wfo-selection">
    <strong>{name(value.model)}</strong>
    {" · "}{zh?"单项上限":"Position cap"} {pct(value.max_position_pct)}
    {value.target_investment_pct!==undefined&&<>
      {" · "}{zh?"目标投资":"Invest"} {pct(value.target_investment_pct)}
      {" · "}{zh?"股票上限":"Equity cap"} {pct(value.equity_class_cap_pct)}
      {" · "}{value.redistribute_excess?(zh?"重新分配":"Reallocate"):(zh?"保留现金":"Keep cash")}
    </>}
  </span>;
}

export default function WalkForwardOptimizer({spec}:{spec:TournamentSourceSpec}){
  const {locale}=useI18n();
  const zh=locale==="zh-CN";
  const l=(en:string,cn:string)=>zh?cn:en;
  const [searchWidth,setSearchWidth]=useState<"focused"|"extended">("focused");
  const [targetCagr,setTargetCagr]=useState("55");
  const [targetSharpe,setTargetSharpe]=useState("2");
  const [riskFree,setRiskFree]=useState("3");
  const [maxDrawdown,setMaxDrawdown]=useState("30");
  const [slippage,setSlippage]=useState("8");
  const [job,setJob]=useState<WalkForwardJob|null>(null);
  const [archive,setArchive]=useState<WalkForwardJob[]>([]);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const specKey=JSON.stringify([spec.version,spec.model,spec.symbols,spec.max_position_pct,spec.delay_sessions,
    spec.target_investment_pct,spec.equity_class_cap_pct,spec.redistribute_excess]);
  useEffect(()=>{setJob(null);setError("");},[specKey]);
  useEffect(()=>{
    let live=true;
    void listWalkForward().then(rows=>{if(live)setArchive(rows);}).catch(()=>{});
    return()=>{live=false;};
  },[specKey]);
  useEffect(()=>{
    if(!job||!["queued","running"].includes(job.status))return;
    let live=true;
    const timer=window.setInterval(()=>{
      void getWalkForward(job.id).then(next=>{
        if(live){
          setJob(current=>current?.id===next.id?next:current);
          if(!["queued","running"].includes(next.status))
            void listWalkForward().then(rows=>{if(live)setArchive(rows);}).catch(()=>{});
        }
      }).catch(e=>{if(live)setError(String(e));});
    },2200);
    return()=>{live=false;window.clearInterval(timer);};
  },[job?.id,job?.status]);
  const submit=async()=>{
    setError("");
    const parse=(value:string,min:number,max:number)=>{
      const n=Number(value);
      if(!value.trim()||!Number.isFinite(n)||n<min||n>max)throw new Error(
        l("Please enter valid research limits.","请输入有效的研究参数。"));
      return n;
    };
    let inputs;
    try{
      inputs={
        spec,search_width:searchWidth,
        target_cagr_pct:parse(targetCagr,10,100),
        target_sharpe:parse(targetSharpe,.5,5),
        risk_free_pct:parse(riskFree,0,15),
        max_drawdown_pct:parse(maxDrawdown,5,60),
        slippage_bps:parse(slippage,0,100),
      };
    }catch(e){setError(String(e));return;}
    setBusy(true);
    try{
      const next=await submitWalkForward(inputs);
      setJob(next);
      setArchive(current=>[next,...current]);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  };
  const open=async(id:string)=>{
    setError("");setBusy(true);
    try{setJob(await getWalkForward(id));}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  };
  const cancel=async()=>{
    if(!job)return;
    setBusy(true);
    try{setJob(await cancelWalkForward(job.id));}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  };
  const result:WalkForwardResult|null=job?.result??null;
  const study=result?.walk_forward;
  const audit=result?.final_audit;
  return <details className="wfo">
    <summary>{l("Walk-forward optimization and unseen-period audit","滚动前推优化与未见数据审计")}</summary>
    <div className="wfo-body">
      <p>{l("Select strategy models and allocation settings on older prices, then test each selection on later sessions. Three rolling validation folds precede one sealed final audit. This is model selection, not AI prediction.",
        "仅使用早期价格选择策略模型及仓位参数，在后续交易日验证。三个滚动验证区间之后进行一次独立留出期审计。这是模型选择，而非AI预测。")}</p>
      <div className="wfo-inputs">
        <label>{l("Search breadth","搜索范围")}
          <select value={searchWidth} onChange={e=>setSearchWidth(e.target.value as typeof searchWidth)}>
            <option value="focused">{l("Focused · up to 12 configurations","精简 · 最多12组配置")}</option>
            <option value="extended">{l("Extended · up to 24 configurations","扩展 · 最多24组配置")}</option>
          </select></label>
        <label>{l("Target annual CAGR (%)","目标年复合增长率（%）")}
          <input type="number" min="10" max="100" step="1" value={targetCagr}
            onChange={e=>setTargetCagr(e.target.value)}/></label>
        <label>{l("Target excess Sharpe","目标超额夏普比率")}
          <input type="number" min="0.5" max="5" step="0.1" value={targetSharpe}
            onChange={e=>setTargetSharpe(e.target.value)}/></label>
        <label>{l("Assumed annual risk-free rate (%)","假设年化无风险利率（%）")}
          <input type="number" min="0" max="15" step="0.25" value={riskFree}
            onChange={e=>setRiskFree(e.target.value)}/></label>
        <label>{l("Max training drawdown (%)","训练期最大回撤（%）")}
          <input type="number" min="5" max="60" step="1" value={maxDrawdown}
            onChange={e=>setMaxDrawdown(e.target.value)}/></label>
        <label>{l("Assumed slippage (bps)","假设滑点（基点）")}
          <input type="number" min="0" max="100" step="1" value={slippage}
            onChange={e=>setSlippage(e.target.value)}/></label>
      </div>
      <div className="wfo-actions">
        <button type="button" disabled={busy||job?.status==="queued"||job?.status==="running"}
          aria-busy={busy} onClick={()=>void submit()}>
          {l("Run walk-forward optimization","运行滚动前推优化")}
        </button>
        {job&&["queued","running"].includes(job.status)&&<button type="button"
          disabled={busy} onClick={()=>void cancel()}>{l("Cancel study","取消研究")}</button>}
      </div>
      {error&&<p role="alert" className="wfo-error">{error}</p>}
      {job&&<p role="status" className="wfo-status">
        {l("Study status","研究状态")}: {job.status} · {job.stage} · {job.progress}%
        {job.error_code&&" · "+job.error_code}
      </p>}
      {job?.status==="queued"&&<p>{l("Run start-local.ps1 to keep the private research worker active. The study never places broker orders.",
        "请使用 start-local.ps1 保持本地研究工作进程运行。该研究不会自动下单。")}</p>}
      {result?.status==="insufficient_history"&&<p className="wfo-error">
        {l("This portfolio does not have enough overlapping daily observations for a credible multi-fold test.",
          "该组合缺少足够的共同日线数据，无法进行可信的多折验证。")} {result.sessions_available} {l("sessions available","个交易日可用")}。
        {result.minimum_requirements}
      </p>}
      {result?.status==="no_eligible_candidate"&&<p className="wfo-error">
        {l("No eligible selection under these research risk constraints.","当前研究风险限制下无合格候选。")} {result.reason}
      </p>}
      {study&&audit&&<>
        <div className="wfo-headline">
          <div><small>{l("Validation fold success","验证期盈利区间")}</small>
            <strong>{study.positive_folds}/{study.fold_count}</strong></div>
          <div><small>{l("Walk-forward CAGR","滚动验证年复合增长")}</small>
            <strong>{pct(study.aggregate_objectives.cagr_pct)}</strong></div>
          <div><small>{l("Walk-forward excess Sharpe","滚动验证超额夏普")}</small>
            <strong>{dec(study.aggregate_objectives.excess_sharpe)}</strong></div>
          <div><small>{l("Walk-forward max drawdown","滚动验证最大回撤")}</small>
            <strong>{pct(study.aggregate_drawdown_pct)}</strong></div>
          <div><small>{l("Untouched audit CAGR","独立审计期复合增长")}</small>
            <strong>{pct(audit.objectives.cagr_pct)}</strong></div>
          <div><small>{l("Untouched audit excess Sharpe","独立审计期超额夏普")}</small>
            <strong>{dec(audit.objectives.excess_sharpe)}</strong></div>
        </div>
        <h5>{l("Training selections and unseen validation","训练期选择与未见数据验证")}</h5>
        <div className="wfo-scroll"><table><thead><tr>
          <th>{l("Fold","折")}</th><th>{l("Unseen period","未见数据区间")}</th>
          <th>{l("Model and allocation selected","所选模型与配置")}</th>
          <th>{l("Unseen return","未见收益")}</th><th>{l("CAGR","复合增长率")}</th>
          <th>{l("Excess Sharpe","超额夏普")}</th><th>{l("Drawdown","回撤")}</th>
        </tr></thead><tbody>{study.folds.map(f=><tr key={f.fold}>
          <td>{f.fold}</td>
          <td>{f.out_of_sample_start} – {f.out_of_sample_end}</td>
          <td><Selection value={f.selected} locale={locale}/></td>
          <td>{pct(f.out_of_sample_return_pct)}</td>
          <td>{pct(f.out_of_sample_objectives.cagr_pct)}</td>
          <td>{dec(f.out_of_sample_objectives.excess_sharpe)}</td>
          <td>{pct(f.out_of_sample_drawdown_pct)}</td>
        </tr>)}</tbody></table></div>
        <h5>{l("Stitched normalized validation index","拼接后的标准化验证指数")}</h5>
        <Plot data={study.curve} description={l("Compound index of separate walk-forward fold returns",
          "分段滚动验证收益复合指数")}/>
        <p className="wfo-disclaimer">{l("Each fold resets to virtual starting capital and zero positions. The index chains percentage returns; it is not a continuous executable position ledger.",
          "每折均重新以虚拟本金和零持仓开始。图表按收益率拼接，并非连续可执行的真实持仓账本。")}</p>
        <h5>{l("Sealed final audit","封存的最终审计")}</h5>
        <p>{audit.start_date} – {audit.end_date} · {audit.sessions} {l("sessions","交易日")}.{" "}
          {l("Selected using only pre-audit observations:","仅使用审计前数据确定的配置：")}{" "}
          <Selection value={audit.selected} locale={locale}/></p>
        <div className="wfo-headline">
          <div><small>{l("Audit total return","审计期总收益")}</small><strong>{pct(audit.return_pct)}</strong></div>
          <div><small>{l("Audit maximum drawdown","审计期最大回撤")}</small><strong>{pct(audit.drawdown_pct)}</strong></div>
          <div><small>{l("Extra slippage return","更高滑点收益")}</small><strong>{pct(audit.stress_return_pct)}</strong></div>
          <div><small>{l("Historical target observation","历史目标观察")}</small>
            <strong>{audit.observed_targets_met?l("Met historically","历史观察达标"):
              l("Not met","未达标")}</strong></div>
        </div>
        <Plot data={audit.curve} description={l("Untouched final audit equity curve","独立最终审计净值曲线")}/>
        <h5>{l("Multiple testing and confidence","多重测试与结果可信度")}</h5>
        <p>{l("Configurations tested per selection","每次选择尝试的配置")}: {result.model_search?.candidate_count}.
          {" "}{l("Total training evaluations","训练期累计评估次数")}: {result.model_search?.total_train_evaluations}.</p>
        <p>{l("Illustrative Bonferroni-adjusted one-sided p-value","示意性 Bonferroni 校正单侧 p 值")}:{" "}
          {study.multiplicity_approximation.bonferroni_approx_p?.toFixed(5)??"N/A"}.
          {" "}{l("This approximation assumes independent Gaussian returns and is not Deflated Sharpe, PBO or proof of an edge.",
            "这一近似假设收益独立且服从正态分布，不是调整后的夏普比率、PBO，也不能证明存在可靠超额收益。")}</p>
        <details className="wfo-limit"><summary>{l("Model limitations and execution assumptions","模型限制与执行假设")}</summary>
          {result.limitations?.map((item,i)=><p key={i}>{item}</p>)}
        </details>
      </>}
      <details className="wfo-history"><summary>{l("Previous private walk-forward studies","过往私人滚动前推研究")} ({archive.length})</summary>
        {archive.length===0?<p>{l("No studies saved yet.","尚无已保存研究。")}</p>:
          archive.slice(0,20).map(item=><button type="button" key={item.id} disabled={busy}
            onClick={()=>void open(item.id)}>
            {new Date(item.created_at).toLocaleString()} · {item.status}
          </button>)}
      </details>
      <p className="wfo-disclaimer">{l("All results are local historical research, never brokerage executions or guaranteed 50–60% annual returns. Forward paper monitoring is still required.",
        "全部结果均为本地历史研究，不是真实券商交易，也不能保证每年获得50–60%收益。正式使用前仍需开展前向模拟监控。")}</p>
    </div>
  </details>;
}
