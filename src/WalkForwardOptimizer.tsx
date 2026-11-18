import {useEffect,useMemo,useState} from "react";
import {useI18n} from "./i18n";
import {submitWalkForward,getWalkForward,listWalkForward,cancelWalkForward} from "./tournamentApi";
import type {TournamentSourceSpec,WalkForwardJob,WalkForwardResult,WalkForwardSelection} from "./tournamentApi";
import "./walkForwardOptimizer.css";

const pct=(value:number|null|undefined)=>value==null||!Number.isFinite(value)?"N/A":value.toFixed(2)+"%";
const dec=(value:number|null|undefined)=>value==null||!Number.isFinite(value)?"N/A":value.toFixed(2);
const name=(value:string)=>value.replaceAll("_"," ").replace(/\b\w/g,c=>c.toUpperCase());

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
    <strong>{value.model==="blended_portfolio"?
      (zh?"组合策略":"Blended portfolio"):name(value.model)}</strong>
    {value.sleeves&&<span className="wfo-sleeves">
      {value.sleeves.map((s,i)=><span key={s.model}>
        {i>0?" + ":""}{name(s.model)} {pct(s.weight_pct)}
      </span>)}
    </span>}
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
  const preAuditDiagnostics=result?.model_search?.pre_audit_selection_diagnostics;
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
        <h5>{l("Annual consistency diagnostics","年度收益一致性诊断")}</h5>
        <p>{l("Rolling 252-session returns overlap and are not independent annual observations. Partial calendar years are excluded from the full-year worst-case statistic.",
          "滚动252个交易日收益区间相互重叠，并非独立年度观测。未满整年的日历年度不会计入完整年度最差收益。")}</p>
        <div className="wfo-headline">
          <div><small>{l("Worst rolling 12-month return","最差滚动12个月收益")}</small>
            <strong>{pct(study.consistency?.worst_rolling_12m_pct)}</strong></div>
          <div><small>{l("Rolling windows meeting growth target","滚动窗口达到增长目标比例")}</small>
            <strong>{pct(study.consistency?.target_hit_rolling_window_pct)}</strong></div>
          <div><small>{l("Worst complete calendar year","最差完整日历年")}</small>
            <strong>{pct(study.consistency?.worst_complete_calendar_year_pct)}</strong></div>
          <div><small>{l("Complete years evaluated","已评估的完整年份")}</small>
            <strong>{study.consistency?.complete_calendar_years??0}</strong></div>
          <div><small>{l("Final audit worst rolling year","最终审计最差滚动年度")}</small>
            <strong>{pct(audit.consistency?.worst_rolling_12m_pct)}</strong></div>
          <div><small>{l("Final audit complete calendar years","最终审计完整日历年")}</small>
            <strong>{audit.consistency?.complete_calendar_years??0}</strong></div>
        </div>
        {(study.consistency?.calendar_years?.length??0)>0&&
          <details className="wfo-limit">
            <summary>{l("Calendar-year breakdown, partial years flagged","日历年收益明细，标注不完整年份")}</summary>
            <div className="wfo-scroll"><table className="wfo-year-table"><thead><tr>
              <th>{l("Year","年份")}</th><th>{l("Observed sessions","已观察交易日")}</th>
              <th>{l("Return","收益率")}</th><th>{l("Coverage","覆盖情况")}</th>
            </tr></thead><tbody>
              {study.consistency?.calendar_years.map(y=><tr key={y.year}>
                <td>{y.year}</td><td>{y.sessions}</td><td>{pct(y.return_pct)}</td>
                <td>{y.complete?l("Near-complete year","接近完整年度"):l("Partial year","不完整年度")}</td>
              </tr>)}
            </tbody></table></div>
          </details>}
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
          <div><small>{l("Delayed execution + higher slippage","延迟执行及更高滑点")}</small><strong>{pct(audit.stress_return_pct)}</strong></div>
          <div><small>{l("Historical target observation","历史目标观察")}</small>
            <strong>{audit.observed_targets_met?l("Met historically","历史观察达标"):
              l("Not met","未达标")}</strong></div>
        </div>
        <Plot data={audit.curve} description={l("Untouched final audit equity curve","独立最终审计净值曲线")}/>
        {(audit.prior_selected_comparison?.length??0)>0&&<>
          <h5>{l("Three portfolios selected before the final audit","在最终审计前选定的三类组合")}</h5>
          <p>{l("Highest training growth, highest training Sharpe and balanced risk-adjusted score are selected using pre-audit prices only. Audit outcomes below do not reselect the winning portfolio.",
            "最高训练期增长率、最高训练期夏普及均衡风险收益评分都只使用审计前价格选定。下方审计结果不会重新选择获胜组合。")}</p>
          <div className="wfo-objective-grid">
            {audit.prior_selected_comparison?.map(item=><article key={item.objective}>
              <strong>{item.objective==="highest_growth"?l("Highest growth","最高增长"):
                item.objective==="highest_sharpe"?l("Highest Sharpe","最高夏普"):
                l("Balanced risk and return","均衡风险收益")}</strong>
              <p><Selection value={item.selected} locale={locale}/></p>
              <div><small>{l("Training CAGR","训练期复合增长率")}</small>
                <b>{pct(item.training_objectives.cagr_pct)}</b></div>
              <div><small>{l("Training excess Sharpe","训练期超额夏普")}</small>
                <b>{dec(item.training_objectives.excess_sharpe)}</b></div>
              <div><small>{l("Audit CAGR","审计期复合增长率")}</small>
                <b>{pct(item.audit_objectives.cagr_pct)}</b></div>
              <div><small>{l("Audit excess Sharpe","审计期超额夏普")}</small>
                <b>{dec(item.audit_objectives.excess_sharpe)}</b></div>
              <div><small>{l("Audit drawdown","审计期回撤")}</small>
                <b>{pct(item.audit_drawdown_pct)}</b></div>
            </article>)}
          </div>
        </>}
        <h5>{l("Pre-audit selection-bias diagnostics","审计前选择偏差诊断")}</h5>
        {result.model_search?.pre_audit_selection_diagnostics&&(()=>{
          const diagnostics=result.model_search.pre_audit_selection_diagnostics;
          const dsr=diagnostics.deflated_sharpe;
          const pbo=diagnostics.pbo;
          return <>
            <p>{l("Computed only from pre-audit candidate equity curves. The final audit was excluded. These tests estimate selection bias; they do not establish an investable edge.",
              "仅使用最终审计前的候选组合净值曲线计算，不包含最终审计数据。这些检验用于估计选择偏差，不能证明策略具有可交易的超额收益。")}</p>
            <div className="wfo-headline">
              <div><small>{l("Estimated deflated Sharpe probability","估计调整后夏普概率")}</small>
                <strong>{pct(dsr.probability_pct)}</strong></div>
              <div><small>{l("Multiple-testing Sharpe threshold","多重检验夏普阈值")}</small>
                <strong>{dec(dsr.expected_max_sharpe)}</strong></div>
              <div><small>{l("CSCV overfitting probability (PBO)","CSCV 过拟合概率（PBO）")}</small>
                <strong>{pct(pbo.estimated_pbo_pct)}</strong></div>
              <div><small>{l("CSCV partitions evaluated","已评估 CSCV 分区")}</small>
                <strong>{pbo.evaluated_splits}</strong></div>
              <div><small>{l("Distinct candidate return paths","不同候选收益路径数")}</small>
                <strong>{pbo.distinct_candidates}</strong></div>
              <div><small>{l("Eligible diagnostic runs","诊断有效候选")}</small>
                <strong>{diagnostics.valid_candidate_curves}/{diagnostics.attempted_candidates}</strong></div>
            </div>
            <p className="wfo-disclaimer">{l("Deflated Sharpe relies on approximate independent, identically distributed returns and an independence-based trial threshold. CSCV reorders pre-audit blocks rather than replaying time in chronological order. N/A means evidence is insufficient.",
              "调整后夏普依赖收益独立同分布及基于独立检验的近似阈值。CSCV 对审计前数据块进行非时间顺序的组合验证，不能替代真实的滚动前推检验。N/A 表示证据不足。")}</p>
          </>;
        })()}
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
