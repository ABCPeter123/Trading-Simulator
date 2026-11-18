import {useCallback,useEffect,useState} from "react";
import {useI18n} from "./i18n";
import {changePaperForwardState,createPaperForward,evaluatePaperForward,
        getPaperForward,listPaperForward} from "./paperForwardApi";
import type {PaperForwardOverview,PaperForwardDetail} from "./paperForwardApi";
import "./paperForward.css";

const display=(n:number|null|undefined,suffix="")=>
  n==null||!Number.isFinite(n)?"N/A":n.toLocaleString(undefined,{maximumFractionDigits:2})+suffix;

export default function PaperForwardMonitor({sourceJobId}:{sourceJobId?:string}){
  const {locale}=useI18n();
  const say=(en:string,zh:string)=>locale==="zh-CN"?zh:en;
  const [list,setList]=useState<PaperForwardOverview[]>([]);
  const [selected,setSelected]=useState<PaperForwardDetail|null>(null);
  const [capital,setCapital]=useState("100000");
  const [drawdown,setDrawdown]=useState("30");
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const load=useCallback(async()=>{
    const records=await listPaperForward();
    setList(records);
    if(selected?.id){
      const match=records.find(r=>r.id===selected.id);
      if(match)setSelected(await getPaperForward(match.id));
    }
  },[selected?.id]);
  useEffect(()=>{
    let active=true;
    void load().catch(e=>{if(active)setError(String(e));});
    const timer=window.setInterval(()=>{
      if(active)void load().catch(()=>{});
    },30000);
    return()=>{active=false;window.clearInterval(timer);};
  },[load]);
  const update=async(action:()=>Promise<unknown>)=>{
    setBusy(true);setError("");
    try{await action();await load();}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  };
  const start=()=>{
    const n=Number(capital),d=Number(drawdown);
    if(!capital.trim()||!drawdown.trim()||!Number.isFinite(n)||n<100||n>1e9||
      !Number.isFinite(d)||d<5||d>60){
      setError(say("Enter valid capital and drawdown limits.","请输入有效的本金与回撤限制。"));
      return;
    }
    if(!sourceJobId)return;
    void update(async()=>{
      const created=await createPaperForward(sourceJobId,n,d);
      setSelected(await getPaperForward(created.id));
    });
  };
  const open=(id:string)=>void update(async()=>setSelected(await getPaperForward(id)));
  return <section className="pf-monitor">
    <h3>{say("Forward-paper monitoring","前向模拟跟踪")}</h3>
    <p>{say("Freeze a completed walk-forward selection and begin measuring only sessions observed after activation. Estimated next-open orders, not broker trades. Historical research and actual confirmed fills remain separate.",
      "冻结已完成滚动研究中的选定策略，仅衡量启动后新出现的交易日。以次日开盘价模拟成交，并非实际券商交易；历史研究与真实成交记录完全分离。")}</p>
    {sourceJobId&&<div className="pf-controls">
      <label>{say("Paper capital (USD)","模拟本金（美元）")}
        <input type="number" min="100" max="1000000000" value={capital}
          onChange={e=>setCapital(e.target.value)}/></label>
      <label>{say("Drawdown stop (%)","回撤止损（%）")}
        <input type="number" min="5" max="60" value={drawdown}
          onChange={e=>setDrawdown(e.target.value)}/></label>
      <button type="button" disabled={busy} onClick={start}>
        {say("Start forward paper from this selection","按当前选定策略启动前向模拟")}
      </button>
    </div>}
    {error&&<p role="alert" className="pf-error">{error}</p>}
    <div className="pf-archive">
      <div className="pf-heading"><h4>{say("Private paper portfolios","私人模拟组合")} ({list.length})</h4>
        <button type="button" disabled={busy} onClick={()=>void update(async()=>{})}>
          {say("Refresh","刷新")}</button>
      </div>
      {!list.length&&<p>{say("No forward-paper portfolios started yet.","尚未启动任何前向模拟组合。")}</p>}
      {list.map(item=><button className="pf-item" type="button" key={item.id}
        disabled={busy} onClick={()=>open(item.id)}>
        <strong>{item.model.replaceAll("_"," ")} · {item.status}</strong>
        <span>{item.symbols.length} {say("instruments","只标的")} ·
          {item.observed_sessions} {say("observed sessions","个已观察交易日")} ·
          {say("Equity","净值")} {display(item.equity)} USD</span>
        <small>{say("Started","启动于")} {item.starting_session} ·
          {say("Last complete","最近完成")} {item.last_session}</small>
      </button>)}
    </div>
    {selected&&<div className="pf-detail">
      <h4>{say("Observed paper evidence","模拟交易观察记录")}</h4>
      <div className="pf-metrics">
        <div><small>{say("Paper CAGR, annualized","模拟年复合增长率")}</small>
          <strong>{display(selected.statistics.cagr_pct,"%")}</strong></div>
        <div><small>{say("Paper excess Sharpe","模拟超额夏普")}</small>
          <strong>{display(selected.statistics.excess_sharpe)}</strong></div>
        <div><small>{say("Drawdown from paper peak","模拟回撤")}</small>
          <strong>{display(selected.current_drawdown_pct,"%")}</strong></div>
        <div><small>{say("Gross exposure","总敞口")}</small>
          <strong>{display(selected.gross_exposure_pct,"%")}</strong></div>
        <div><small>{say("Financing and short costs (USD)","融资与借券成本（美元）")}</small>
          <strong>{display(selected.financing_paid)} USD</strong></div>
        <div><small>{say("Audit versus paper CAGR gap","历史审计与模拟年化差距")}</small>
          <strong>{display(selected.drift.cagr_gap_pct,"%")}</strong></div>
      </div>
      <p>{say("Modeled execution delay","模拟成交延迟")}: {selected.delay_sessions}
        {say(" completed sessions"," 个交易日")} ·
        {say("Pending simulated fill","待模拟成交")}: {selected.pending_execution?say("Yes","是"):say("No","否")}.
        {" "}{say("Drift diagnostics need at least 30 observed sessions and remain descriptive.",
          "偏差指标至少需要30个实际观察交易日，仅用于描述。")}</p>
      {selected.last_error&&<p role="alert" className="pf-error">{selected.last_error}</p>}
      {selected.status==="active"&&<div className="pf-actions">
        <button disabled={busy} type="button"
          onClick={()=>void update(async()=>setSelected(await getPaperForward(
            (await evaluatePaperForward(selected.id)).id)))}>
          {say("Check newly completed sessions","检查新完成的交易日")}</button>
        <button disabled={busy} type="button"
          onClick={()=>void update(()=>changePaperForwardState(selected.id,"paused"))}>
          {say("Pause permanently","暂停本次观察")}</button>
        <button disabled={busy} type="button"
          onClick={()=>void update(()=>changePaperForwardState(selected.id,"retired"))}>
          {say("Retire study","归档本次研究")}</button>
      </div>}
      <div className="pf-scroll"><table><thead><tr>
        <th>{say("Session","日期")}</th><th>{say("Equity USD","净值（美元）")}</th>
        <th>{say("Drawdown","回撤")}</th><th>{say("Gross exposure","总敞口")}</th>
      </tr></thead><tbody>{selected.marks.slice(-40).reverse().map(item=><tr key={item.session}>
        <td>{item.session}</td><td>{display(item.value)} USD</td>
        <td>{display(item.drawdown_pct,"%")}</td>
        <td>{display(item.gross_pct,"%")}</td>
      </tr>)}</tbody></table></div>
      <details><summary>{say("Simulated fills, not broker orders","模拟成交记录，非券商订单")} ({selected.fills.length})</summary>
        <div className="pf-scroll"><table><thead><tr>
          <th>{say("Day","日期")}</th><th>{say("Asset","标的")}</th>
          <th>{say("Action","操作")}</th><th>{say("Shares","股数")}</th>
          <th>{say("Estimated price USD","估计美元价格")}</th>
        </tr></thead><tbody>{selected.fills.slice(-100).reverse().map((fill,i)=><tr key={i}>
          <td>{fill.session}</td><td>{fill.symbol.toUpperCase()}</td><td>{fill.action}</td>
          <td>{fill.quantity}</td><td>{display(fill.price)} USD</td>
        </tr>)}</tbody></table></div>
      </details>
      <p className="pf-disclaimer">{say("One-day-delayed completed candles are used. Fills are modeled from subsequently observed opens, after spreads and slippage. No share locate, real fills, account margin reconciliation or guaranteed Sharpe is implied.",
        "使用至少延迟一天的完整日线。成交按后续观察到的开盘价估计，并含点差和滑点。不代表已借到股票、真实成交、券商保证金核对或保证夏普表现。")}</p>
    </div>}
  </section>;
}
