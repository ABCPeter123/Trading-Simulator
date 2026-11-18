import {useEffect,useMemo,useState} from "react";
import {useI18n} from "./i18n";
import {submitWalkForward,getWalkForward,listWalkForward,cancelWalkForward} from "./tournamentApi";
import type {TournamentSourceSpec,WalkForwardJob,WalkForwardResult,WalkForwardSelection} from "./tournamentApi";
import "./walkForwardOptimizer.css";
import PaperForwardMonitor from "./PaperForwardMonitor";

const pct=(value:number|null|undefined)=>value==null||!Number.isFinite(value)?"N/A":value.toFixed(2)+"%";
const dec=(value:number|null|undefined)=>value==null||!Number.isFinite(value)?"N/A":value.toFixed(2);
const money=(value:number|null|undefined)=>value==null||!Number.isFinite(value)?"N/A":
  new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(value);
const name=(value:string)=>value.replaceAll("_"," ").replace(/\b\w/g,c=>c.toUpperCase());

const reviewLabels:Record<string,[string,string]>={
  below_cash_hurdle:["Annual growth below assumed cash rate","年收益低于假设现金利率"],
  nonpositive_excess_sharpe:["Nonpositive risk-adjusted excess return","风险调整后超额收益未转正"],
  below_same_basket_baseline:["Underperformed same-basket equal weight","弱于同资产等权基准"],
  below_spy_price_benchmark:["Underperformed SPY price benchmark","弱于 SPY 价格基准"],
  low_invested_exposure:["Low invested capital","投资资本占比偏低"],
  high_turnover_weak_growth:["High turnover with weak growth","高换手与低增长并存"],
  same_model_all_folds:["Same allocation across all folds","所有验证期选择相同配置"],
  unstable_position_cap:["Sensitive to position cap changes","对持仓上限变动敏感"],
  weak_multiple_tested_sharpe:["Weak multiple-testing-adjusted Sharpe","多重检验调整后的夏普信号偏弱"],
  few_eligible_training_models:["Too few eligible training candidates","训练期合格候选数量偏少"],
};
const reviewObservationZh:Record<string,string>={
  below_cash_hurdle:"审计期年增长低于配置的固定现金收益门槛。",
  nonpositive_excess_sharpe:"在假定现金利率下，审计期超额夏普不为正。",
  below_same_basket_baseline:"在完全相同资产与日期上，选中组合表现弱于等权持有。",
  below_spy_price_benchmark:"选中组合表现弱于同期 SPY 买入持有的仅价格基准。",
  low_invested_exposure:"平均总投资敞口低于初始资本的 50%。",
  high_turnover_weak_growth:"相对初始资本交易频繁，但年增长偏低。",
  same_model_all_folds:"所有前推验证区间均独立选中了相同模型配置，候选多样性有限。",
  unstable_position_cap:"小幅调整持仓上限会明显改变审计前的历史年增长。",
  weak_multiple_tested_sharpe:"近似调整后夏普不足以支持可靠的风险调整后优势。",
  few_eligible_training_models:"极少数配置通过审计前的风险或敞口筛选。",
};
const reviewMethodsZh:Record<string,string>={
  compare_exposure_and_costs:"检查训练期现金、资产类别上限与交易成本，对照同资产等权组合。调整参数前先明确研究假设。",
  benchmark_over_new_sessions:"冻结策略版本，继续收集新的模拟交易时段，并用完全相同日期的基准评价。",
  audit_data_provenance:"增加模型复杂度前，核查复权价格、已退市标的、历史成分股、币种转换与数据来源。",
};


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
  const [searchWidth,setSearchWidth]=useState<"focused"|"extended"|"comprehensive">("focused");
  const [baseCurrency,setBaseCurrency]=useState<"USD"|"CAD">(spec.base_currency??"USD");
  const [commission,setCommission]=useState(String(spec.commission_usd??0));
  const [fxBps,setFxBps]=useState(String(spec.fx_conversion_bps??150));
  const [targetCagr,setTargetCagr]=useState("55");
  const [targetSharpe,setTargetSharpe]=useState("2");
  const [riskFree,setRiskFree]=useState("3");
  const [maxDrawdown,setMaxDrawdown]=useState("30");
  const [minGrowth,setMinGrowth]=useState("10");
  const [minExcessGrowth,setMinExcessGrowth]=useState("0");
  const [minInvested,setMinInvested]=useState("50");
  const [slippage,setSlippage]=useState(String(spec.slippage_bps??8));
  const [job,setJob]=useState<WalkForwardJob|null>(null);
  const [archive,setArchive]=useState<WalkForwardJob[]>([]);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const specKey=JSON.stringify([spec.version,spec.model,spec.symbols,spec.max_position_pct,spec.delay_sessions,
    spec.target_investment_pct,spec.equity_class_cap_pct,spec.redistribute_excess,
    spec.sleeves,spec.base_currency,spec.slippage_bps,spec.commission_usd,spec.fx_conversion_bps]);
  useEffect(()=>{
    setJob(null);setError("");
    setBaseCurrency(spec.base_currency??"USD");setCommission(String(spec.commission_usd??0));
    setFxBps(String(spec.fx_conversion_bps??150));setSlippage(String(spec.slippage_bps??8));
  },[specKey]);
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
        minimum_training_cagr_pct:parse(minGrowth,0,100),
        minimum_excess_cagr_pct_points:parse(minExcessGrowth,0,30),
        min_average_invested_pct:parse(minInvested,0,100),
        slippage_bps:parse(slippage,0,100),
        base_currency:baseCurrency,
        commission_usd:parse(commission,0,30),
        fx_conversion_bps:parse(fxBps,0,300),
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
            <option value="comprehensive">{l("Comprehensive · up to 48 configurations","全面 · 最多48组配置")}</option>
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
        <label>{l("Minimum training CAGR (%)","最低训练期年复合增长（%）")}
          <input type="number" min="0" max="100" step="1" value={minGrowth}
            onChange={e=>setMinGrowth(e.target.value)}/></label>
        <label>{l("Minimum CAGR above cash assumption (percentage points)",
                    "超出假设现金利率的最低增长差值（百分点）")}
          <input type="number" min="0" max="30" step=".5" value={minExcessGrowth}
            onChange={e=>setMinExcessGrowth(e.target.value)}/></label>
        <label>{l("Minimum average invested capital (%)",
                    "最低平均已投资资本（%）")}
          <input type="number" min="0" max="100" step="5" value={minInvested}
            onChange={e=>setMinInvested(e.target.value)}/></label>
        <label>{l("Account funding currency","账户资金币种")}
          <select value={baseCurrency} onChange={e=>setBaseCurrency(e.target.value as "USD"|"CAD")}>
            <option value="USD">USD</option><option value="CAD">CAD</option>
          </select></label>
        <label>{l("Commission per order (USD)","每笔佣金（美元）")}
          <input type="number" min="0" max="30" step="0.1" value={commission}
            onChange={e=>setCommission(e.target.value)}/></label>
        <label>{l("Cross-currency conversion (bps)","跨币种换汇（基点）")}
          <input type="number" min="0" max="300" value={fxBps}
            onChange={e=>setFxBps(e.target.value)}/></label>
        <label>{l("Assumed slippage (bps)","假设滑点（基点）")}
          <input type="number" min="0" max="100" step="1" value={slippage}
            onChange={e=>setSlippage(e.target.value)}/></label>
      </div>
      <p className="wfo-disclaimer">{l(
        "Growth and exposure requirements are hard training-only eligibility gates. The aspirational CAGR and Sharpe remain scoring targets. No eligible candidate means no selected strategy. Minimum exposure never forces the engine to invest when signals say cash. A controlled 25/35/45/55% drawdown frontier plus your chosen limit compares only the three pre-audit folds.",
        "增长和敞口要求是仅使用训练期数据的硬性筛选门槛。目标 CAGR 和夏普仍是评分目标。若没有合格候选则不选择策略。最低敞口要求不会强制策略在现金信号下买入。25/35/45/55%回撤限制及自定义限制仅在最终审计前的三个验证区间进行对比。"
      )}</p>
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
      {result?.rejection_diagnostics&&<details className="wfo-limit" open>
        <summary>{l("Training rejection breakdown, no qualified strategy",
          "训练期拒绝原因，没有合格策略")}</summary>
        <p>{l("The optimizer refused to promote a strategy that missed the configured requirements. No audit was used to rescue or select a failing model.",
          "优化器不会把不符合设定要求的策略视为优胜策略，也不会利用审计期数据挽救或重新选择。")}</p>
        <div className="wfo-headline">
          <div><small>{l("Eligible","合格")}</small><strong>{result.rejection_diagnostics.eligible_count}</strong></div>
          <div><small>{l("Tested","测试总数")}</small><strong>{result.rejection_diagnostics.attempted_count}</strong></div>
        </div>
        <div className="wfo-scroll"><table><thead><tr>
          <th>{l("Reason","拒绝原因")}</th><th>{l("Candidates","候选数量")}</th>
        </tr></thead><tbody>{Object.entries(result.rejection_diagnostics.rejection_reasons).map(([reason,count])=>
          <tr key={reason}><td>{name(reason)}</td><td>{count}</td></tr>)}</tbody></table></div>
      </details>}
      {result?.status==="no_eligible_candidate"&&result.model_search?.pre_audit_risk_frontier&&
        <details className="wfo-limit" open>
          <summary>{l("Risk-limit sensitivity, training and pre-audit folds only",
            "风险限制敏感性，仅训练期及最终审计前验证")}</summary>
          <p>{l("All risk limits are tested under the same minimum growth, investment and execution assumptions. No alternate model was evaluated on the final audit, and this failed study did not select any strategy.",
            "所有回撤限制均使用相同的最低增长率、投资敞口和执行成本假设。没有对最终审计期测试替代模型，本次研究也没有选出任何策略。")}</p>
          <div className="wfo-scroll"><table><thead><tr>
            <th>{l("Training drawdown cap","训练期回撤上限")}</th>
            <th>{l("Qualified historical folds","合格的历史验证区间")}</th>
            <th>{l("Stitched fold CAGR","验证期拼接年复合增长")}</th>
            <th>{l("Final pre-audit training eligible","最终审计前训练合格数")}</th>
          </tr></thead><tbody>{result.model_search.pre_audit_risk_frontier.experiments.map(x=>
            <tr key={x.max_training_drawdown_pct}>
              <td>{pct(x.max_training_drawdown_pct)}</td>
              <td>{x.folds_with_eligible_candidate}/{x.fold_count}</td>
              <td>{pct(x.validation_cagr_pct)}</td>
              <td>{x.pre_audit_final_training_eligible_count}</td>
            </tr>)}</tbody></table></div>
        </details>}
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
        {result.eligibility_policy&&<>
          <h5>{l("Hard training qualification gates","训练期硬性资格筛选")}</h5>
          <div className="wfo-headline">
            <div><small>{l("Minimum training CAGR","最低训练期增长率")}</small>
              <strong>{pct(result.eligibility_policy.minimum_training_cagr_pct)}</strong></div>
            <div><small>{l("CAGR above cash assumption","超过现金假设的增长率")}</small>
              <strong>{pct(result.eligibility_policy.minimum_excess_cagr_pct_points)}</strong></div>
            <div><small>{l("Average invested exposure minimum","最低平均投资敞口")}</small>
              <strong>{pct(result.eligibility_policy.min_average_invested_pct)}</strong></div>
          </div>
          <p className="wfo-disclaimer">{l("Every candidate must satisfy all three gates on past training periods, plus the configured drawdown and margin limits. This is screening, not a promise of future performance.",
            "每个候选都必须在历史训练期满足三项门槛，以及所设回撤及保证金要求。这是筛选机制，不代表未来收益保证。")}</p>
        </>}
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
        {study.folds.some(f=>f.original_tournament_reference)&&
          <details className="wfo-limit" open>
            <summary>{l("Original tournament model vs walk-forward selections",
              "原竞赛模型与滚动优化模型对照")}</summary>
            <p>{l("This replays the tournament-selected source model on the same sessions and cost assumptions as the walk-forward candidates. It is retrospective: the source model may have been selected using data from these dates, so its returns are NOT fresh unseen evidence. Neither its returns nor its earlier risk-gate results change the optimizer's selections.",
              "将竞赛选中的原始模型按相同日期及执行成本重新模拟。此比较属于事后分析：原模型可能已利用这些日期的数据做出选择，因此其收益并非新的未见数据证据。该模型的收益及训练期风险筛选结果均不会改变滚动优化结果。")}</p>
            <div className="wfo-scroll"><table><thead><tr>
              <th>{l("Period","期间")}</th>
              <th>{l("Walk-forward selected","滚动优化模型")}</th>
              <th>{l("Original tournament model","原竞赛模型")}</th>
              <th>{l("Original training gate","原模型训练期筛选")}</th>
              <th>{l("Original training drawdown","原模型训练期回撤")}</th>
              <th>{l("Original invested capital","原模型平均投资")}</th>
            </tr></thead><tbody>{study.folds.map(f=><tr key={f.fold}>
              <td>{l("Fold","验证期")} {f.fold}</td>
              <td>{pct(f.out_of_sample_return_pct)}</td>
              <td>{pct(f.original_tournament_reference?.return_pct)}</td>
              <td>{f.original_tournament_reference?.training_gate?
                name(f.original_tournament_reference.training_gate):
                l("Unavailable","不可用")}</td>
              <td>{pct(f.original_tournament_reference?.training_drawdown_pct)}</td>
              <td>{pct(f.original_tournament_reference?.average_invested_pct)}</td>
            </tr>)}</tbody></table></div>
          </details>}
        <details className="wfo-limit">
          <summary>{l("Fold-by-fold benchmarks, execution and exposure",
            "各验证期基准、执行成本及敞口")}</summary>
          <p>{l("Each benchmark uses the identical basket and unseen fold dates, with independent capital resets. The cash comparison is a fixed-rate hypothetical hurdle, not actual historical cash returns.",
            "每个基准使用完全相同的标的和未见验证区间，各区间独立重置本金。现金对照是固定利率假设，不代表真实历史现金收益。")}</p>
          <div className="wfo-scroll"><table><thead><tr>
            <th>{l("Fold","验证期")}</th>
            <th>{l("Selected return","所选策略收益")}</th>
            <th>{l("Same-basket equal weight","相同资产等权")}</th>
            <th>{l("SPY price-only return","SPY 仅价格收益")}</th>
            <th>{l("Fixed-rate cash hurdle","固定现金利率门槛")}</th>
            <th>{l("Gross invested","总投资敞口")}</th>
            <th>{l("Turnover","交易换手")}</th>
            <th>{l("Fees and financing","费用及融资")}</th>
          </tr></thead><tbody>{study.folds.map(f=><tr key={f.fold}>
            <td>{f.fold}</td><td>{pct(f.out_of_sample_return_pct)}</td>
            <td>{pct(f.unseen_benchmark_comparison?.benchmarks.find(b=>b.id==="same_basket_equal_weight")?.return_pct)}</td>
            <td>{pct(f.unseen_spy_price_benchmark?.return_pct)}</td>
            <td>{pct(f.unseen_benchmark_comparison?.benchmarks.find(b=>b.id==="constant_cash_hurdle")?.return_pct)}</td>
            <td>{pct(f.unseen_exposure_and_costs?.average_gross_invested_pct)}</td>
            <td>{pct(f.unseen_exposure_and_costs?.turnover_pct_of_initial_capital)}</td>
            <td>{money(f.unseen_exposure_and_costs?.explicit_fees_and_financing_usd)}</td>
          </tr>)}</tbody></table></div>
        </details>
        {result.model_search?.pre_audit_risk_frontier&&<section className="wfo-limit">
          <h5>{l("Controlled drawdown-limit comparison, pre-audit only",
            "受控回撤上限对比，仅限最终审计前")}</h5>
          <p>{l("The candidate grid, growth and exposure gates, and execution costs are fixed. Only the maximum allowed training drawdown changes. Each alternative is selected using earlier training prices and observed on the following three historical folds. The final audit is NOT replayed for alternate caps. Inspecting these fold returns does not create a fresh unseen test.",
            "候选范围、增长和敞口门槛以及执行成本均固定，仅改变训练期允许的最大回撤。每项方案只依据此前训练期选择，并在随后三个历史验证区间观测。不会针对不同回撤上限重新测试最终审计期。查看这些收益不构成新的独立未见验证。")}</p>
          <div className="wfo-scroll"><table><thead><tr>
            <th>{l("Training drawdown cap","训练回撤上限")}</th>
            <th>{l("Eligible folds","合格验证期")}</th>
            <th>{l("Stitched CAGR","拼接后年复合增长")}</th>
            <th>{l("Excess Sharpe","超额夏普")}</th>
            <th>{l("Validation drawdown","验证期回撤")}</th>
            <th>{l("Final training eligible","最终训练期合格数量")}</th>
          </tr></thead><tbody>{result.model_search.pre_audit_risk_frontier.experiments.map(x=>
            <tr key={x.max_training_drawdown_pct}>
              <td>{pct(x.max_training_drawdown_pct)} {x.is_configured_limit?l("(configured)","（当前设置）"):""}</td>
              <td>{x.folds_with_eligible_candidate}/{x.fold_count}</td>
              <td>{pct(x.validation_cagr_pct)}</td>
              <td>{dec(x.validation_excess_sharpe)}</td>
              <td>{pct(x.validation_drawdown_pct)}</td>
              <td>{x.pre_audit_final_training_eligible_count}</td>
            </tr>)}</tbody></table></div>
          <p className="wfo-disclaimer">{l("When a risk limit has fewer than three eligible folds, its stitched result is unavailable rather than cherry-picking successful periods. This diagnostic does not select the final model or rank models on audit data.",
            "若某风险上限有少于三个合格区间，拼接结果标记为不可用，不会只选择成功的时间段。此诊断不会选择最终模型，也不按审计期收益排序。")}</p>
        </section>}
        <h5>{l("Stitched normalized validation index","拼接后的标准化验证指数")}</h5>
        <Plot data={study.curve} description={l("Compound index of separate walk-forward fold returns",
          "分段滚动验证收益复合指数")}/>
        <p className="wfo-disclaimer">{l("Each fold resets to virtual starting capital and zero positions. The index chains percentage returns; it is not a continuous executable position ledger.",
          "每折均重新以虚拟本金和零持仓开始。图表按收益率拼接，并非连续可执行的真实持仓账本。")}</p>
        {result.execution_assumptions&&<p className="wfo-disclaimer">
          {l("Execution model","执行成本模型")}: {result.execution_assumptions.base_currency} ·
          {" "}{l("Commission","佣金")} {"$"}{result.execution_assumptions.commission_usd} ·
          {" "}{l("FX","换汇")} {result.execution_assumptions.fx_conversion_bps} bps ·
          {" "}{l("Slippage","滑点")} {result.execution_assumptions.slippage_bps} bps.
        </p>}
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
        {audit.original_tournament_reference&&<details className="wfo-limit" open>
          <summary>{l("Original tournament candidate: retrospective final-period comparison",
            "原竞赛候选：最终期间的事后比较")}</summary>
          <p>{l("This keeps the original tournament model and settings unchanged instead of reselecting another strategy. The historical final period is already observed and is NOT a new sealed audit of the original model.",
            "此处保留原竞赛模型及设置，不重新选择其他策略。历史最终区间已被观察，因此不是原模型新的独立审计。")}</p>
          <div className="wfo-headline">
            <div><small>{l("Original model total return","原模型总收益")}</small>
              <strong>{pct(audit.original_tournament_reference.return_pct)}</strong></div>
            <div><small>{l("Original model CAGR","原模型年复合增长")}</small>
              <strong>{pct(audit.original_tournament_reference.cagr_pct)}</strong></div>
            <div><small>{l("Original model drawdown","原模型最大回撤")}</small>
              <strong>{pct(audit.original_tournament_reference.drawdown_pct)}</strong></div>
            <div><small>{l("Original model average invested","原模型平均投资比例")}</small>
              <strong>{pct(audit.original_tournament_reference.average_invested_pct)}</strong></div>
          </div>
          <p>{l("Prior-period risk gate","审计前风险筛选")}:{" "}
            {audit.original_tournament_reference.training_gate?
            name(audit.original_tournament_reference.training_gate):
            l("Unavailable","不可用")}.{" "}
            {l("Prior-period drawdown","审计前回撤")}:{" "}
            {pct(audit.original_tournament_reference.training_drawdown_pct)}.{" "}
            {l("Prior-period score","审计前得分")}:{" "}
            {dec(audit.original_tournament_reference.training_score)}.</p>
          <p className="wfo-disclaimer">{l("A model chosen by a different tournament is not an independent ex-ante walk-forward contender. This comparison is for diagnosis only and cannot be used to claim the original tournament backtest was verified.",
            "通过其他竞赛选出的模型并非独立的事前滚动验证候选。此比较仅供诊断，不能视为原竞赛回测已经获得独立验证。")}</p>
        </details>}
        {audit.benchmark_comparison&&<>
          <h5>{l("Same-period baseline comparison","同区间基准比较")}</h5>
          <p>{l("The same-basket equal-weight baseline is a separately simulated long-only portfolio with identical instruments and session dates. The cash hurdle compounds your assumed constant annual rate. Neither benchmark participates in model selection.",
            "相同资产等权基准在同一标的和日期上独立模拟多头组合。现金门槛按假定的固定年利率复利计算。两者均不参与模型选择。")}</p>
          <div className="wfo-scroll"><table><thead><tr>
            <th>{l("Portfolio / reference","组合或参考")}</th>
            <th>{l("Total return","总收益")}</th><th>{l("CAGR","年复合增长")}</th>
            <th>{l("Maximum drawdown","最大回撤")}</th>
            <th>{l("Excess Sharpe","超额夏普")}</th>
          </tr></thead><tbody>
            <tr><td>{l("Selected portfolio","所选组合")}</td>
              <td>{pct(audit.return_pct)}</td><td>{pct(audit.objectives.cagr_pct)}</td>
              <td>{pct(audit.drawdown_pct)}</td><td>{dec(audit.objectives.excess_sharpe)}</td></tr>
            {audit.market_benchmark?.status==="available"&&<tr>
              <td>{l("SPY buy and hold, price only","SPY 买入持有，仅价格")}</td>
              <td>{pct(audit.market_benchmark.return_pct)}</td>
              <td>{pct(audit.market_benchmark.cagr_pct)}</td>
              <td>{pct(audit.market_benchmark.drawdown_pct)}</td>
              <td>{dec(audit.market_benchmark.excess_sharpe)}</td>
            </tr>}
            {audit.benchmark_comparison.benchmarks.map(b=><tr key={b.id}>
              <td>{b.id==="same_basket_equal_weight"?l("Same-basket equal weight","同资产等权"):l("Hypothetical fixed-rate cash","假设固定利率现金")}</td>
              <td>{pct(b.return_pct)}</td><td>{pct(b.cagr_pct)}</td>
              <td>{pct(b.drawdown_pct)}</td><td>{dec(b.excess_sharpe)}</td>
            </tr>)}
          </tbody></table></div>
          <p className="wfo-disclaimer">{audit.market_benchmark?.status==="available"?
            l("SPY is loaded independently after the strategy selection is locked. Sessions match exactly, with one modeled opening purchase. Dividends are not explicitly reinvested and price adjustments depend on the provider. Source: ",
              "SPY 在锁定策略选择后独立读取。交易日严格匹配，模拟首日开盘买入。股息未单独再投资，复权方式取决于数据提供方。数据来源： ")+audit.market_benchmark.source:
            l("SPY reference unavailable on all required dates. No missing observations were filled or invented.",
              "所需日期的 SPY 数据不完整。缺失数据未填补或伪造。")}</p>
        </>}
        {audit.exposure_and_costs&&<>
          <h5>{l("Why did the portfolio earn this return?","组合收益表现归因")}</h5>
          <p>{l("Exposure is calculated from the simulated ledger. Gross investment averages daily holdings; cash and asset classes are measured at rebalance snapshots. Turnover is total buy and sell notional divided by starting capital, not annualized.",
            "敞口由模拟交易账本计算。总投资为每日持仓平均值；现金及资产类别按再平衡时点测算。换手率为总买卖金额除以初始本金，不是年化数值。")}</p>
          <div className="wfo-headline">
            <div><small>{l("Average gross investment","平均总投资敞口")}</small>
              <strong>{pct(audit.exposure_and_costs.average_gross_invested_pct)}</strong></div>
            <div><small>{l("Average net investment","平均净投资敞口")}</small>
              <strong>{pct(audit.exposure_and_costs.average_net_exposure_pct)}</strong></div>
            <div><small>{l("Cash at rebalances","再平衡时点平均现金")}</small>
              <strong>{pct(audit.exposure_and_costs.average_rebalance_cash_pct)}</strong></div>
            <div><small>{l("Turnover / starting capital","换手额 / 初始本金")}</small>
              <strong>{pct(audit.exposure_and_costs.turnover_pct_of_initial_capital)}</strong></div>
            <div><small>{l("Explicit costs and financing","显性费用及融资")}</small>
              <strong>{money(audit.exposure_and_costs.explicit_fees_and_financing_usd)}</strong></div>
            <div><small>{l("Trades executed","模拟成交笔数")}</small>
              <strong>{audit.exposure_and_costs.trade_count}</strong></div>
          </div>
          <div className="wfo-scroll"><table><thead><tr>
            <th>{l("Asset class","资产类别")}</th>
            <th>{l("Average gross weight at rebalances","再平衡时平均总权重")}</th>
          </tr></thead><tbody>{Object.entries(audit.exposure_and_costs.average_category_gross_pct).map(([group,value])=>
            <tr key={group}><td>{name(group)}</td><td>{pct(value)}</td></tr>)}</tbody></table></div>
        </>}
        {audit.selection_score_breakdown&&<details className="wfo-limit">
          <summary>{l("Pre-audit selection score contributions","审计前选择评分分解")}</summary>
          <p>{l("Only pre-audit training contributes to this score. Negative components are penalties, not realized losses.",
            "此评分只使用审计前训练数据。负值是评分扣分，不是已实现损失。")}</p>
          <div className="wfo-scroll"><table><thead><tr>
            <th>{l("Component","评分项")}</th><th>{l("Points","分值")}</th>
          </tr></thead><tbody>{Object.entries(audit.selection_score_breakdown.components).map(([key,value])=>
            <tr key={key}><td>{name(key.replace(/_points$/,""))}</td><td>{dec(value)}</td></tr>)}
          </tbody></table></div>
        </details>}
        {(audit.execution_stress_scenarios?.length??0)>0&&<div>
          <h5>{l("Execution robustness on the sealed audit","最终审计中的执行稳健性")}</h5>
          <p>{l("Stress outcomes are diagnostics only. They do not reselect the portfolio.",
            "压力测试仅用于诊断，不会重新选择组合。")}</p>
          <div className="wfo-scroll"><table><thead><tr><th>{l("Scenario","情景")}</th>
            <th>{l("Delay, sessions","延迟交易日")}</th><th>{l("Slippage, bps","滑点基点")}</th>
            <th>{l("Return","收益率")}</th></tr></thead>
            <tbody>{audit.execution_stress_scenarios?.map(x=><tr key={x.name}>
              <td>{name(x.name)}</td><td>{x.delay_sessions}</td>
              <td>{x.slippage_bps.toFixed(1)}</td><td>{pct(x.return_pct)}</td>
            </tr>)}</tbody></table></div></div>}
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
        {result.model_search?.pre_audit_candidate_leaderboard&&<details className="wfo-limit">
          <summary>{l("Why did this strategy win? Training-only candidate rankings",
            "该策略为何胜出？仅训练期候选排名")}</summary>
          <p>{l("These results are calculated before the audit. A higher return outside these dates cannot change the selected candidate.",
            "这些结果只使用审计前的数据。审计期更高的收益不会改变已选模型。")}</p>
          <div className="wfo-scroll"><table><thead><tr>
            <th>{l("Rank","名次")}</th><th>{l("Training model","训练期模型")}</th>
            <th>{l("Score","得分")}</th><th>{l("Training CAGR","训练期年增长")}</th>
            <th>{l("Excess Sharpe","超额夏普")}</th><th>{l("Drawdown","回撤")}</th>
            <th>{l("Turnover","换手")}</th><th>{l("Invested","投资敞口")}</th>
          </tr></thead><tbody>{result.model_search.pre_audit_candidate_leaderboard.best_by_training_score.map(x=>
            <tr key={x.rank}><td>{x.rank}</td>
              <td><Selection value={x.config} locale={locale}/></td>
              <td>{dec(x.training_score)}</td><td>{pct(x.training_cagr_pct)}</td>
              <td>{dec(x.training_excess_sharpe)}</td><td>{pct(x.training_drawdown_pct)}</td>
              <td>{pct(x.training_turnover_pct)}</td><td>{pct(x.training_average_invested_pct)}</td>
            </tr>)}</tbody></table></div>
          <p>{l("Rejected candidate count","未通过筛选的候选数量")}:{" "}
            {result.model_search.pre_audit_candidate_leaderboard.rejected_count}.
            {" "}{Object.entries(result.model_search.pre_audit_candidate_leaderboard.rejection_reasons)
              .map(([reason,count])=>name(reason)+": "+count).join(" · ")}</p>
        </details>}
        {result.model_search?.pre_audit_parameter_stability&&<details className="wfo-limit">
          <summary>{l("Parameter stability, pre-audit only",
            "参数稳定性，仅审计前")}</summary>
          <p>{l("The selected position cap is perturbed by five percentage points without changing the audited model. This is a sensitivity check, not another unseen test. Do not choose new parameters based on the final audit.",
            "在不改变已审计模型的前提下，单项仓位上限上下调整五个百分点。此处是敏感性分析，并非新的未见测试，不能根据最终审计调整模型。")}</p>
          <div className="wfo-scroll"><table><thead><tr>
            <th>{l("Maximum asset weight","最大单项权重")}</th>
            <th>{l("Prior-only CAGR","审计前年复合增长")}</th>
            <th>{l("Excess Sharpe","超额夏普")}</th>
            <th>{l("Drawdown","回撤")}</th>
            <th>{l("Turnover","换手")}</th>
          </tr></thead><tbody>{result.model_search.pre_audit_parameter_stability.variants.map(x=>
            <tr key={x.max_position_pct}><td>{pct(x.max_position_pct)} {x.selected_setting?l("(selected)","（已选择）"):""}</td>
              <td>{pct(x.cagr_pct)}</td><td>{dec(x.excess_sharpe)}</td>
              <td>{pct(x.drawdown_pct)}</td><td>{pct(x.turnover_pct)}</td>
            </tr>)}</tbody></table></div>
          <p>{l("CAGR range across valid neighbors","有效相邻参数的年增长率跨度")}:{" "}
            {pct(result.model_search.pre_audit_parameter_stability.cagr_range_pct_points)}.</p>
        </details>}
        {result.research_review?.status==="diagnostic_only"&&<section className="wfo-limit">
          <h5>{l("Private research review: findings and next experiments",
            "私人研究复盘：主要发现与下一步实验")}</h5>
          <p>{l("This is a deterministic local diagnostic, not an AI-generated forecast. It never launches jobs, changes strategy parameters or submits orders.",
            "这是本地确定性诊断，不是 AI 预测。不会自动启动任务、更改策略参数或下单。")}</p>
          <div className="wfo-headline">
            <div><small>{l("High-priority findings","高优先级发现")}</small>
              <strong>{result.research_review.summary?.critical_findings??0}</strong></div>
            <div><small>{l("Training candidates eligible","训练期合格候选")}</small>
              <strong>{result.research_review.summary?.training_candidates_eligible??"N/A"}</strong></div>
          </div>
          {(result.research_review.findings?.length??0)>0?
            <div className="wfo-scroll"><table><thead><tr>
              <th>{l("Severity","重要程度")}</th>
              <th>{l("Observed issue","观察到的问题")}</th>
              <th>{l("Evidence period","证据时期")}</th>
            </tr></thead><tbody>{result.research_review.findings?.map(f=><tr key={f.code}>
              <td>{f.severity==="high"?l("High","高"):f.severity==="medium"?l("Medium","中"):l("Info","提示")}</td>
              <td>{(reviewLabels[f.code]??[name(f.code),name(f.code)])[zh?1:0]}
                <p>{zh?(reviewObservationZh[f.code]??f.observation):f.observation}</p>
              </td><td>{f.basis==="sealed_audit"?l("Already opened audit","已查看的审计期"):
                l("Pre-audit only","审计前")}</td>
            </tr>)}</tbody></table></div>:
            <p>{l("No rule-based concerns met the current thresholds. This is not proof of a profitable strategy.",
              "没有达到目前的规则诊断阈值，但这不能证明策略有盈利优势。")}</p>}
          <h5>{l("Proposed follow-up experiments","建议的后续实验")}</h5>
          <div className="wfo-objective-grid">
            {result.research_review.next_experiments?.map(p=><article key={p.id}>
              <strong>{p.id==="compare_exposure_and_costs"?l("Audit cash and trading costs","检查现金配置及交易成本"):
                p.id==="benchmark_over_new_sessions"?l("Collect fresh forward-paper evidence","收集新的前向模拟证据"):
                l("Verify historical data provenance","核查历史数据来源")}</strong>
              <p>{zh?(reviewMethodsZh[p.id]??p.method):p.method}</p>
            </article>)}
          </div>
          <p className="wfo-disclaimer">{l("The final audit has been seen and cannot be reused as untouched evidence for revisions. New tests need truly fresh sessions. All suggestions require deliberate action.",
            "最终审计已经被查看，不能在修改策略后再次称作未见数据。新的验证需要真正新产生的交易日数据，所有建议均需主动执行。")}</p>
        </section>}
        <h5>{l("Pre-audit selection-bias diagnostics","审计前选择偏差诊断")}</h5>
        {preAuditDiagnostics&&(()=>{
          const diagnostics=preAuditDiagnostics;
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
      {result?.status==="completed"&&<PaperForwardMonitor sourceJobId={job?.id}/>}
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
