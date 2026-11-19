import {useEffect,useMemo,useState} from "react";
import {useI18n} from "./i18n";
import {createCustomPeriodStudy,getCustomPeriodStudy,cancelCustomPeriodStudy} from "./tournamentApi";
import type {CustomPeriodJob,CustomPeriodResult,TournamentSourceSpec} from "./tournamentApi";
import "./customStrategyAnalysis.css";

const standardModels=new Set(["equal_weight","inverse_volatility","trend_filter","relative_momentum","volatility_target","blended_portfolio"]);
const money=(x:number)=>new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(x);
const pct=(x:number|null|undefined)=>x==null||!Number.isFinite(x)?"N/A":x.toFixed(2)+"%";
const num=(x:number|null|undefined)=>x==null||!Number.isFinite(x)?"N/A":x.toFixed(2);
const shortDate=(seconds:number)=>new Date(seconds*1000).toISOString().slice(0,10);

function EquityChart({result,title}:{result:CustomPeriodResult;title:string}){
  const primary=result.equity_curve, baseline=result.benchmark_curve;
  const data=useMemo(()=>{
    const count=primary.length;
    if(!count)return {strategy:"",benchmark:"",max:0,min:0};
    const vals=[...primary.map(x=>x.value),...baseline.map(x=>x.value)];
    const min=Math.min(...vals),max=Math.max(...vals);
    const span=Math.max(max-min,1);
    const path=(series:typeof primary)=>{
      const stride=Math.max(1,Math.ceil(series.length/360));
      const points=series.filter((_,i)=>i%stride===0||i===series.length-1);
      return points.map((p,j)=>{
        const index=Math.min(series.length-1,j*stride);
        const x=36+688*index/Math.max(1,series.length-1);
        const y=174-148*(p.value-min)/span;
        return (j?"L":"M")+x.toFixed(2)+","+y.toFixed(2);
      }).join(" ");
    };
    return {strategy:path(primary),benchmark:path(baseline),min,max};
  },[primary,baseline]);
  if(!primary.length)return null;
  return <div className="csa-chart">
    <svg viewBox="0 0 760 215" role="img" aria-label={title} preserveAspectRatio="xMidYMid meet">
      <title>{title}</title>
      <line x1="36" y1="174" x2="724" y2="174" stroke="#526779" strokeWidth="1"/>
      <line x1="36" y1="26" x2="724" y2="26" stroke="#304a5c" strokeWidth="1"/>
      <text x="32" y="22" fill="#bed2df" fontSize="12">{money(data.max)}</text>
      <text x="32" y="191" fill="#bed2df" fontSize="12">{money(data.min)}</text>
      <path d={data.benchmark} stroke="#9a9da6" strokeWidth="2" fill="none"/>
      <path d={data.strategy} stroke="#60cbbb" strokeWidth="2.5" fill="none"/>
      <text x="36" y="207" fill="#bed2df" fontSize="11">{shortDate(primary[0].time)}</text>
      <text x="724" y="207" fill="#bed2df" fontSize="11" textAnchor="end">{shortDate(primary[primary.length-1].time)}</text>
    </svg>
    <div className="csa-legend"><span className="csa-strategy-dot"/>Strategy / 策略 {baseline.length>0&&<><span className="csa-benchmark-dot"/>Equal-weight benchmark / 等权基准</>}</div>
  </div>;
}

export default function CustomStrategyAnalysis({spec,initialJob=null}: {spec:TournamentSourceSpec;initialJob?:CustomPeriodJob|null}){
  const {locale}=useI18n();
  const l=(english:string,chinese:string)=>locale==="zh-CN"?chinese:english;
  const key=JSON.stringify([spec.model,spec.symbols,spec.max_position_pct,
    spec.delay_sessions,spec.rebalance_sessions,spec.version,spec.sleeves,
    spec.base_currency,spec.slippage_bps,spec.commission_usd,spec.fx_conversion_bps]);
  const standard=standardModels.has(spec.model);
  const [start,setStart]=useState("");
  const [end,setEnd]=useState("");
  const [position,setPosition]=useState(String(spec.max_position_pct));
  const [delay,setDelay]=useState<1|2>(spec.delay_sessions);
  const [slippage,setSlippage]=useState(String(spec.slippage_bps??8));
  const [investment,setInvestment]=useState(String(spec.target_investment_pct??95));
  const [equityCap,setEquityCap]=useState(String(spec.equity_class_cap_pct??70));
  const [redistribute,setRedistribute]=useState(Boolean(spec.redistribute_excess));
  const [job,setJob]=useState<CustomPeriodJob|null>(null);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  useEffect(()=>{
    setJob(null);setError("");setPosition(String(spec.max_position_pct));
    setDelay(spec.delay_sessions);setSlippage(String(spec.slippage_bps??8));
    setInvestment(String(spec.target_investment_pct??95));
    setEquityCap(String(spec.equity_class_cap_pct??70));
    setRedistribute(Boolean(spec.redistribute_excess));
  },[key]);
  useEffect(()=>{
    if(initialJob)setJob(initialJob);
  },[initialJob?.id]);
  useEffect(()=>{
    if(!job||!["queued","running"].includes(job.status))return;
    let alive=true;
    const timer=window.setInterval(()=>{
      void getCustomPeriodStudy(job.id).then(next=>{if(alive)setJob(current=>current?.id===next.id?next:current);})
        .catch(e=>{if(alive)setError(e instanceof Error?e.message:String(e));});
    },1800);
    return()=>{alive=false;window.clearInterval(timer);};
  },[job?.id,job?.status]);
  const run=async()=>{
    setError("");
    const p=Number(position),s=Number(slippage),gross=Number(investment),cap=Number(equityCap);
    if((start&&end&&start>end)||(start&&!/^\d{4}-\d{2}-\d{2}$/.test(start))||
       (end&&!/^\d{4}-\d{2}-\d{2}$/.test(end))){
      setError(l("Choose a valid date range.","请选择有效的日期范围。"));return;
    }
    if(!Number.isFinite(p)||p<10||p>50||!Number.isFinite(s)||s<0||s>100||
       (standard&&(!Number.isFinite(gross)||gross<5||gross>100||!Number.isFinite(cap)||cap<10||cap>100))){
      setError(l("Please check the position, investment, concentration and slippage limits.","请检查仓位、投资比例、类别集中度和滑点设置。"));return;
    }
    setBusy(true);
    try{
      const next=await createCustomPeriodStudy({
        spec,start_date:start||null,end_date:end||null,
        max_position_pct:p,delay_sessions:delay,slippage_bps:s,
        ...(standard?{target_investment_pct:gross,equity_class_cap_pct:cap,
          redistribute_excess:redistribute}:{}),
      });
      setJob(next);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  };
  const cancel=async()=>{
    if(!job)return;
    setBusy(true);
    try{setJob(await cancelCustomPeriodStudy(job.id));}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  };
  const result=job?.result;
  const m=result?.metrics,p=result?.periods;
  return <section className="csa" aria-label={l("Custom historical backtest","自定义历史回测")}>
    <header>
      <h4>{l("Custom timeframe and performance analysis","自选时间范围与绩效分析")}</h4>
      <p>{l("Re-run this exact strategy on dates you choose. Results use the same historical execution engine as the tournament, but do not change its original rankings.",
        "按自行选择的日期重新运行此策略。结果使用与策略竞赛相同的历史执行引擎，但不会改变原有排名。")}</p>
    </header>
    <div className="csa-form">
      <label>{l("Start date (optional)","起始日期（选填）")}
        <input type="date" value={start} onChange={e=>setStart(e.target.value)}/></label>
      <label>{l("End date (optional)","结束日期（选填）")}
        <input type="date" value={end} onChange={e=>setEnd(e.target.value)}/></label>
      <label>{l("Maximum position (%)","单项仓位上限（%）")}
        <input type="number" min="10" max="50" step="1" value={position} onChange={e=>setPosition(e.target.value)}/></label>
      <label>{l("Execution delay","成交延迟")}
        <select value={delay} onChange={e=>setDelay(Number(e.target.value) as 1|2)}>
          <option value={1}>{l("Next shared opening","下一共同交易日开盘")}</option>
          <option value={2}>{l("One extra session lag","额外滞后一个交易日")}</option>
        </select></label>
      <label>{l("Assumed slippage (bps)","假设滑点（基点）")}
        <input type="number" min="0" max="100" step="1" value={slippage} onChange={e=>setSlippage(e.target.value)}/></label>
      {standard&&<>
        <label>{l("Target invested capital (%)","目标投资比例（%）")}
          <input type="number" min="5" max="100" step="1" value={investment} onChange={e=>setInvestment(e.target.value)}/></label>
        <label>{l("Maximum equity-class exposure (%)","股票类别总敞口上限（%）")}
          <input type="number" min="10" max="100" step="1" value={equityCap} onChange={e=>setEquityCap(e.target.value)}/></label>
        <label className="csa-check">
          <input type="checkbox" checked={redistribute} onChange={e=>setRedistribute(e.target.checked)}/>
          {l("Reinvest unused weight into eligible assets","将未分配权重重新投入符合条件的资产")}
        </label>
      </>}
    </div>
    <p className="csa-small">{standard?
      l("For fully invested research: set target invested capital to 100%, equity-class cap to 100%, and enable redistribution. This does not override per-asset limits or buy assets that fail the strategy signal.",
        "若希望接近满仓：将目标投资比例及股票类别上限均设为100%，并勾选重新分配。此设置不会突破单项仓位上限，也不会买入不符合信号的资产。"):
      l("This model has its own hedge, short, or leverage budgets. Investment and category targets are defined by its strategy rules; you can still customize dates, position caps, delay, and slippage.",
        "此高级模型有自身的对冲、做空或杠杆敞口预算。投资及类别目标由策略规则决定；您仍可调整日期、单项仓位上限、延迟和滑点。")}</p>
    <div className="csa-actions">
      <button type="button" className="csa-run" disabled={busy||job?.status==="queued"||job?.status==="running"} onClick={()=>void run()}>
        {busy?l("Submitting...","正在提交……"):l("Run custom historical analysis","运行自定义历史回测")}</button>
      {job&&["queued","running"].includes(job.status)&&
        <button type="button" disabled={busy} onClick={()=>void cancel()}>{l("Cancel study","取消任务")}</button>}
    </div>
    {error&&<p className="csa-error" role="alert">{error}</p>}
    {job&&!result&&<p className="csa-status" role="status">{l("Study","分析任务")}: {job.status} · {job.stage} · {job.progress}% {job.error_code?("· "+job.error_code):""}</p>}
    {job?.status==="queued"&&<p className="csa-small">{l(
      "The local research worker must be running to process queued studies. Start the local app with start-local.ps1 and keep it running; this is not a live brokerage order.",
      "排队任务需要本地研究工作进程运行。请使用 start-local.ps1 启动本地程序并保持运行；这不是实际券商订单。")}</p>}
    {job?.status==="failed"&&<p className="csa-error" role="alert">{l(
      "The study could not complete. Check the available common historical dates, selected instruments and local market data. You can adjust the settings and rerun.",
      "研究任务未能完成。请检查共同历史日期、所选资产和本地行情数据。可以调整设置后重新运行。")}</p>}
    {result&&m&&p&&<>
      <div className="csa-window"><strong>{l("Actual tested period","实际测试区间")}:</strong> {result.actual_window.start_date} – {result.actual_window.end_date} · {result.actual_window.sessions} {l("shared sessions","个共同交易日")}</div>
      <h5>{l("Performance and risk","收益与风险")}</h5>
      <div className="csa-kpis">
        {[
          [l("Total return","累计收益"),pct(m.return_pct)],
          [l("Ending capital","期末资金"),money(100000*(1+m.return_pct/100))],
          [l("Annualized volatility","年化波动率"),pct(m.annualized_volatility_pct)],
          [l("Maximum drawdown","最大回撤"),pct(m.max_drawdown_pct)],
          [l("Sharpe ratio","夏普比率"),num(m.sharpe)],
          [l("Sortino ratio","索提诺比率"),num(m.sortino)],
          [l("Average invested","平均已投资比例"),pct(m.average_invested_pct)],
          [l("Trading costs","模拟交易成本"),money(m.fees)],
          [l("Trades","成交次数"),String(m.trades)],
          [l("Equal-weight return","等权基准收益"),pct(result.benchmark?.return_pct)],
          [l("Extra-delay stress return","额外延迟压力测试收益"),pct(result.execution_stress?.return_pct)],
          [l("Return versus benchmark","相对基准收益"),pct(result.benchmark?m.return_pct-result.benchmark.return_pct:null)],
        ].map(([title,value])=><div key={title}><small>{title}</small><strong>{value}</strong></div>)}
      </div>
      {Boolean(result.unavailable_comparisons?.length)&&<p className="csa-small" role="note">{l(
        "The selected strategy completed, but some optional reference simulations were unavailable for these dates. Unavailable comparisons show N/A, not an estimated return.",
        "所选策略已完成计算，但部分对照测试在该区间不可用。对应指标显示N/A，而非估算收益。")}</p>}
      <h5>{l("Historical simulated account value","历史模拟账户净值")}</h5>
      <EquityChart result={result} title={l("Historical portfolio equity and available equal-weight benchmark","历史组合净值及可用的等权基准")}/>
      <h5>{l("Worst observed outcomes","历史最差表现")}</h5>
      <div className="csa-kpis">
        {[
          [l("Worst month","最差月份"),p.worst_month.month+" · "+pct(p.worst_month.return_pct)],
          [l("Worst trading day","最差单日"),p.worst_day?pct(p.worst_day.return_pct)+" · "+p.worst_day.end:"N/A"],
          [l("Worst 5-session period","最差连续5交易日"),p.worst_five_sessions?pct(p.worst_five_sessions.return_pct):"N/A"],
          [l("Worst 21-session period","最差连续21交易日"),p.worst_21_sessions?pct(p.worst_21_sessions.return_pct):"N/A"],
          [l("Largest peak-to-trough decline","最大高点至低点跌幅"),pct(p.worst_drawdown.drawdown_pct)],
          [l("Best month","最佳月份"),p.best_month.month+" · "+pct(p.best_month.return_pct)],
        ].map(([title,value])=><div key={title}><small>{title}</small><strong>{value}</strong></div>)}
      </div>
      <h5>{l("Earnings by month","每月收益明细")}</h5>
      <p className="csa-small">{l("Months at the start or end of the selected window may be partial. Earnings are changes in virtual account equity, not realized broker income.",
        "所选区间首月或末月可能不是完整月份。收益金额指虚拟账户净值变化，而非真实券商已实现收入。")}</p>
      <div className="csa-tablewrap"><table><thead><tr>
        <th>{l("Month","月份")}</th><th>{l("Return","收益率")}</th><th>{l("Earnings (USD)","收益金额（美元）")}</th>
        <th>{l("Ending equity","月末净值")}</th><th>{l("Sessions","交易日")}</th>
      </tr></thead><tbody>{p.monthly.map(row=><tr key={row.month}>
        <td>{row.month}</td><td>{pct(row.return_pct)}</td><td>{money(row.pnl_usd)}</td>
        <td>{money(row.ending_equity)}</td><td>{row.observed_sessions}</td>
      </tr>)}</tbody></table></div>
      <p className="csa-small">{l("Historical worst-case results are not a maximum possible future loss. Custom-window outcomes are exploratory and may overlap the tournament's training or validation data.",
        "历史最差表现不代表未来可能发生的最大亏损。自选时间区间属于探索性研究，可能与竞赛训练或验证数据重叠。")}</p>
    </>}
  </section>;
}
