import {useEffect,useMemo,useState} from "react";
import {useI18n} from "./i18n";
import {createIntradayStudy,getIntradayStudy,cancelIntradayStudy} from "./tournamentApi";
import type {TournamentSourceSpec,IntradayStudyJob,IntradayStudyResult,IntradayResolution,IntradayWindow} from "./tournamentApi";
import "./intradayPortfolioResearch.css";

const WINDOWS:Record<IntradayResolution,readonly IntradayWindow[]>={
  "1m":["7D"],
  "5m":["7D","30D","60D"],
  "15m":["7D","30D","60D"],
  "1h":["7D","30D","60D","6M","1Y","2Y"],
};
const CASH_MODELS=new Set(["equal_weight","inverse_volatility","trend_filter","relative_momentum","volatility_target"]);
const pct=(n:number)=>Number.isFinite(n)?n.toFixed(2)+"%":"N/A";
const dollars=(n:number)=>new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(n);

function MiniChart({curves}:{curves:IntradayStudyResult}){
  const paths=useMemo(()=>{
    if(!curves?.equity_curve?.length)return null;
    const a=curves.equity_curve,b=curves.benchmark_curve;
    const all=[...a,...b].map(p=>p.value);
    const bottom=Math.min(...all),top=Math.max(...all);
    const span=Math.max(1,top-bottom);
    const stroke=(data:typeof a)=>data.map((p,i)=>{
      const x=20+(i/Math.max(1,data.length-1))*740;
      const y=178-154*(p.value-bottom)/span;
      return (i===0?"M":"L")+x.toFixed(1)+","+y.toFixed(1);
    }).join(" ");
    return {strategy:stroke(a),benchmark:stroke(b)};
  },[curves]);
  if(!paths)return null;
  return <svg className="ipr-chart" viewBox="0 0 780 200" role="img" aria-label="Intraday simulated portfolio equity and equal-weight control">
    <path d={paths.benchmark} stroke="#a0a9b6" strokeWidth="2" fill="none"/>
    <path d={paths.strategy} stroke="#66d1bd" strokeWidth="2.3" fill="none"/>
  </svg>;
}

export default function IntradayPortfolioResearch({spec}:{spec:TournamentSourceSpec}){
  const {locale}=useI18n();
  const l=(en:string,zh:string)=>locale==="zh-CN"?zh:en;
  const [resolution,setResolution]=useState<IntradayResolution>("5m");
  const [period,setPeriod]=useState<IntradayWindow>("60D");
  const [checks,setChecks]=useState<1|2|4>(2);
  const [slippage,setSlippage]=useState(String(spec.slippage_bps??8));
  const [commission,setCommission]=useState(String(spec.commission_usd??0));
  const [job,setJob]=useState<IntradayStudyJob|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const modelKey=JSON.stringify([spec.symbols,spec.model,spec.max_position_pct,spec.target_investment_pct,
    spec.equity_class_cap_pct,spec.redistribute_excess,spec.base_currency]);
  useEffect(()=>{setJob(null);setError("");},[modelKey]);
  useEffect(()=>{
    if(!job||!["queued","running"].includes(job.status))return;
    let active=true;
    const timer=window.setInterval(()=>{
      void getIntradayStudy(job.id).then(next=>{
        if(active)setJob(current=>current?.id===next.id?next:current);
      }).catch(e=>{if(active)setError(String(e));});
    },2000);
    return()=>{active=false;window.clearInterval(timer);};
  },[job?.id,job?.status]);
  const supported=CASH_MODELS.has(spec.model) && spec.base_currency!=="CAD";
  const run=async()=>{
    setError("");
    const slip=Number(slippage),fee=Number(commission);
    if(!Number.isFinite(slip)||slip<0||slip>100||!Number.isFinite(fee)||fee<0||fee>30){
      setError(l("Check slippage (0-100 bps) and commission (0-30 USD).","检查滑点（0-100基点）与佣金（0-30美元）。"));return;
    }
    setBusy(true);
    try{
      const next=await createIntradayStudy({spec,mode:"intraday",resolution,period,
        checks_per_day:checks,slippage_bps:slip,commission_usd:fee});
      setJob(next);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  };
  const cancel=async()=>{
    if(!job)return;
    setBusy(true);
    try{setJob(await cancelIntradayStudy(job.id));}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  };
  const result=job?.result;
  return <details className="ipr">
    <summary>{l("Intraday portfolio test · actual minute candles","日内组合测试 · 真实分钟K线")}</summary>
    <div className="ipr-body">
      <p>{l("Test the selected allocation model on real intraday candles. Each signal reads completed bars and fills at the following shared candle open. Shorter bars change the model's indicator lookbacks; this is a separate exploratory test, not the original daily strategy's walk-forward audit.",
        "使用真实日内K线测试当前配置模型。每次信号只读取已完成K线，按下一根共同K线开盘价模拟成交。更短周期会改变指标回看时长，此结果是独立探索性测试，不属于原日线策略的滚动验证。")}</p>
      {!supported?<p className="ipr-warning">{l(
        "Intraday testing currently supports cash-funded standard portfolio models in USD. Short, margin and blended strategies retain their daily research engine.",
        "日内测试目前仅支持美元现金账户的标准组合模型。做空、融资及混合策略仍使用日线研究引擎。")}</p>:<>
        <div className="ipr-inputs">
          <label>{l("Candles","K线周期")}
            <select value={resolution} onChange={e=>{
              const next=e.target.value as IntradayResolution;
              setResolution(next);setPeriod(next==="1m"?"7D":next==="1h"?"1Y":"60D");
            }}>
              <option value="1m">{l("1 minute","1分钟")}</option>
              <option value="5m">{l("5 minutes","5分钟")}</option>
              <option value="15m">{l("15 minutes","15分钟")}</option>
              <option value="1h">{l("1 hour","1小时")}</option>
            </select></label>
          <label>{l("Historical window","历史区间")}
            <select value={period} onChange={e=>setPeriod(e.target.value as IntradayWindow)}>
              {WINDOWS[resolution].map(x=><option key={x} value={x}>{x}</option>)}
            </select></label>
          <label>{l("Portfolio checks each trading day","每日组合检查次数")}
            <select value={checks} onChange={e=>setChecks(Number(e.target.value) as 1|2|4)}>
              <option value={1}>{l("1 per day","每天1次")}</option>
              <option value={2}>{l("2 per day","每天2次")}</option>
              <option value={4}>{l("4 per day","每天4次")}</option>
            </select></label>
        </div>
        <details className="ipr-advanced"><summary>{l("Execution costs","成交成本")}</summary>
          <div className="ipr-inputs">
            <label>{l("Slippage (bps per side)","单边滑点（基点）")}
              <input type="number" min="0" max="100" value={slippage} onChange={e=>setSlippage(e.target.value)}/></label>
            <label>{l("Commission per asset order (USD)","每笔资产订单佣金（美元）")}
              <input type="number" min="0" max="30" value={commission} onChange={e=>setCommission(e.target.value)}/></label>
          </div>
        </details>
        <div className="ipr-actions">
          <button type="button" disabled={busy||job?.status==="queued"||job?.status==="running"}
            onClick={()=>void run()}>{l("Run intraday test","运行日内测试")}</button>
          {job&&["queued","running"].includes(job.status)&&
            <button type="button" disabled={busy} onClick={()=>void cancel()}>{l("Cancel","取消")}</button>}
        </div>
        <p className="ipr-small">{l("1-minute history is limited to about seven calendar days. For broader comparisons, use 5/15-minute or 1-hour candles. One check can create multiple asset orders or none.",
          "1分钟历史通常仅覆盖约7个自然日。较长区间请使用5/15分钟或1小时K线。一次检查可以产生多笔资产订单，也可能没有订单。")}</p>
        {error&&<p role="alert" className="ipr-warning">{error}</p>}
        {job&&<p role="status">{l("Study","研究")}: {job.status} · {job.stage} · {job.progress}%{job.error_code?" · "+job.error_code:""}</p>}
        {job?.status==="failed"&&<p className="ipr-warning">{l(
          "The requested portfolio may lack sufficiently aligned real candles, or the data provider may be unavailable. Try fewer USD symbols, a 5/15-minute interval, or a shorter window.",
          "该组合可能缺乏足够的共同真实K线，或数据提供方暂时不可用。请减少美元标的、改用5/15分钟周期或缩短历史区间。")}</p>}
        {result&&<>
          <div className="ipr-kpis">
            {[[l("Simulated return","模拟收益"),pct(result.metrics.return_pct)],
              [l("Maximum drawdown","最大回撤"),pct(result.metrics.max_drawdown_pct)],
              [l("Allocation checks","组合检查次数"),String(result.metrics.checks)],
              [l("Executed asset orders","资产订单数量"),String(result.metrics.trades)],
              [l("Fees (USD)","费用（美元）"),dollars(result.metrics.fees)],
              [l("Equal-weight return","等权基准收益"),pct(result.benchmark.return_pct)]
            ].map(([label,value])=><div key={label}><small>{label}</small><strong>{value}</strong></div>)}
          </div>
          <p className="ipr-small">{result.common_bars} {l("exactly shared real candles,","根真实共同K线，")}
            {" "}{result.metrics.sessions} {l("observed trading dates.","个实际交易日。")}
            {" "}{new Date(result.first_bar*1000).toLocaleDateString()} – {new Date(result.last_bar*1000).toLocaleDateString()}</p>
          <div className="ipr-legend">{l("Portfolio","组合")} <span className="ipr-dot"/>
            {" "}{l("Equal-weight control","等权对照")} <span className="ipr-dot ipr-dot-muted"/></div>
          <MiniChart curves={result}/>
          <details className="ipr-advanced"><summary>{l("Executed order sample","模拟成交样本")} ({result.fills_total})</summary>
            <div className="ipr-scroll"><table><thead><tr>
              <th>{l("Time","时间")}</th><th>{l("Asset","标的")}</th><th>{l("Side","方向")}</th>
              <th>{l("Quantity","数量")}</th><th>{l("Price","价格")}</th>
            </tr></thead><tbody>{result.fills.map((f,i)=><tr key={i}>
              <td>{new Date(f.time*1000).toLocaleString()}</td><td>{f.symbol.toUpperCase()}</td>
              <td>{f.side}</td><td>{f.quantity}</td><td>{dollars(f.price)}</td>
            </tr>)}</tbody></table></div>
          </details>
          <details className="ipr-advanced"><summary>{l("Data provenance and limitations","数据来源与限制")}</summary>
            {Object.entries(result.sources).map(([symbol,info])=>
              <p key={symbol}>{symbol.toUpperCase()}: {info.source} · {info.observed_bars}
                {" "}{l("bars","根K线")}{info.offline_snapshot?" · "+l("archived","本地归档"):""}</p>)}
            <p>{result.execution}</p>
            {result.limitations.map((line,i)=><p key={i}>{line}</p>)}
          </details>
        </>}
      </>}
    </div>
  </details>;
}
