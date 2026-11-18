import {useCallback,useEffect,useState} from "react";
import {useI18n} from "./i18n";
import {changePaperForwardState,createPaperForward,evaluatePaperForward,
        getPaperForward,listPaperForward} from "./paperForwardApi";
import type {PaperForwardOverview,PaperForwardDetail,PaperExecution} from "./paperForwardApi";
import "./paperForward.css";

const display=(n:number|null|undefined,suffix="")=>
  n==null||!Number.isFinite(n)?"N/A":n.toLocaleString(undefined,{maximumFractionDigits:2})+suffix;

function EquityChart({marks,label}:{marks:PaperForwardDetail["marks"];label:string}){
  if(marks.length<2)return null;
  const benchmarkReady=marks.every(m=>m.benchmark_value!=null);
  const values=marks.map(m=>m.value);
  const comparison=benchmarkReady?marks.map(m=>m.benchmark_value as number):[];
  const bottom=Math.min(...values,...comparison),top=Math.max(...values,...comparison);
  const span=Math.max(1,top-bottom);
  const line=(series:number[])=>series.map((value,index)=>{
    const x=8+684*index/(series.length-1);
    const y=149-136*(value-bottom)/span;
    return (index===0?"M":"L")+x.toFixed(2)+","+y.toFixed(2);
  }).join(" ");
  const path=line(values);
  return <svg viewBox="0 0 704 165" className="pf-plot" role="img" aria-label={label}>
    <title>{label}</title>
    {benchmarkReady&&<path d={line(comparison)} stroke="#e1bc7e"
      strokeWidth="1.8" fill="none" strokeDasharray="6 4"
      strokeLinejoin="round" strokeLinecap="round"/>}
    <path d={path} stroke="#6dd3ba" strokeWidth="2.5" fill="none"
      strokeLinejoin="round" strokeLinecap="round"/>
  </svg>;
}

export default function PaperForwardMonitor({sourceJobId}:{sourceJobId?:string}){
  const {locale}=useI18n();
  const say=(en:string,zh:string)=>locale==="zh-CN"?zh:en;
  const [list,setList]=useState<PaperForwardOverview[]>([]);
  const [selected,setSelected]=useState<PaperForwardDetail|null>(null);
  const [capital,setCapital]=useState("100000");
  const [drawdown,setDrawdown]=useState("30");
  const [broker,setBroker]=useState<PaperExecution["broker"]>("wealthsimple");
  const [account,setAccount]=useState<PaperExecution["account_type"]>("cash");
  const [capitalCurrency,setCapitalCurrency]=useState<"USD"|"CAD">("USD");
  const [borrowAssumption,setBorrowAssumption]=useState(false);
  const [timing,setTiming]=useState<PaperExecution["fill_timing"]>("next_open");
  const [marginRate,setMarginRate]=useState("");
  const [shortRate,setShortRate]=useState("6");
  const [slippage,setSlippage]=useState("8");
  const [fxSpread,setFxSpread]=useState("0");
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
    const fields=[marginRate,shortRate,slippage,fxSpread];
    if(fields.some(x=>x.trim()!==""&&(!Number.isFinite(Number(x))||Number(x)<0||Number(x)>500))||
      (marginRate!==""&&Number(marginRate)>100)||
      (shortRate!==""&&Number(shortRate)>100)){
      setError(say("Invalid financing or execution cost.","融资或成交成本参数无效。"));
      return;
    }
    const execution:PaperExecution={
      broker,account_type:account,capital_currency:capitalCurrency,
      borrow_policy:broker==="ibkr"&&account==="margin"&&borrowAssumption
        ?"assume_available_research":"block_unverified",
      fill_timing:timing,
      ...(marginRate.trim()?{margin_rate_pct:Number(marginRate)}:{}),
      ...(shortRate.trim()?{short_borrow_rate_pct:Number(shortRate)}:{}),
      ...(slippage.trim()?{slippage_bps:Number(slippage)}:{}),
      ...(fxSpread.trim()?{fx_spread_bps:Number(fxSpread)}:{}),
    };
    void update(async()=>{
      const created=await createPaperForward(sourceJobId,n,d,execution);
      setSelected(await getPaperForward(created.id));
    });
  };
  const open=(id:string)=>void update(async()=>setSelected(await getPaperForward(id)));
  return <section className="pf-monitor">
    <h3>{say("Forward-paper monitoring","前向模拟跟踪")}</h3>
    <p>{say("Freeze a completed walk-forward selection and begin measuring only sessions observed after activation. Estimated next-open orders, not broker trades. Historical research and actual confirmed fills remain separate.",
      "冻结已完成滚动研究中的选定策略，仅衡量启动后新出现的交易日。以次日开盘价模拟成交，并非实际券商交易；历史研究与真实成交记录完全分离。")}</p>
    {sourceJobId&&<div className="pf-controls">
      <label>{say("Broker research profile","券商模拟配置")}
        <select value={broker} onChange={e=>{
          const next=e.target.value as PaperExecution["broker"];
          setBroker(next);
          setAccount(next==="wealthsimple"?"cash":"margin");
          setBorrowAssumption(false);
          setMarginRate("");
        }}>
          <option value="wealthsimple">Wealthsimple</option>
          <option value="ibkr">Interactive Brokers Canada</option>
          <option value="legacy_research">{say("Generic research","通用研究模拟")}</option>
        </select></label>
      <label>{say("Simulated account","模拟账户")}
        <select value={account} onChange={e=>setAccount(e.target.value as PaperExecution["account_type"])}>
          <option value="cash">{say("Cash only","现金账户")}</option>
          <option value="margin">{say("Margin research","保证金账户")}</option>
        </select></label>
      <label>{say("Funding currency","入金币种")}
        <select value={capitalCurrency}
          onChange={e=>setCapitalCurrency(e.target.value as "CAD"|"USD")}>
          <option value="USD">USD</option><option value="CAD">CAD</option>
        </select></label>
      <label>{say("Paper capital","模拟本金")} ({capitalCurrency})
        <input type="number" min="100" max="1000000000" value={capital}
          onChange={e=>setCapital(e.target.value)}/></label>
      <label>{say("Price used for delayed simulated fill","延迟模拟成交价")}
        <select value={timing} onChange={e=>setTiming(e.target.value as PaperExecution["fill_timing"])}>
          <option value="next_open">{say("Later session open","后续交易日开盘")}</option>
          <option value="next_close">{say("Later session close, stress scenario","后续交易日收盘，压力场景")}</option>
        </select></label>
      <label>{say("Margin interest %, annual (blank = broker model)","融资年利率%，留空使用券商模型")}
        <input type="number" min="0" max="100" step=".1" value={marginRate}
          placeholder={broker==="wealthsimple"?"Tiered USD":"5.13"}
          onChange={e=>setMarginRate(e.target.value)}/></label>
      <label>{say("Short borrowing %, annual, assumed","假设融券年利率%")}
        <input type="number" min="0" max="100" step=".1" value={shortRate}
          onChange={e=>setShortRate(e.target.value)}/></label>
      <label>{say("Slippage (basis points)","滑点（基点）")}
        <input type="number" min="0" max="500" step="1" value={slippage}
          onChange={e=>setSlippage(e.target.value)}/></label>
      <label>{say("Extra FX spread (basis points)","额外换汇点差（基点）")}
        <input type="number" min="0" max="500" step="1" value={fxSpread}
          onChange={e=>setFxSpread(e.target.value)}/></label>
      {broker==="ibkr"&&account==="margin"&&<label className="pf-borrow">
        <input type="checkbox" checked={borrowAssumption}
          onChange={e=>setBorrowAssumption(e.target.checked)}/>
        {say("Assume shortable shares for research only, without verified locate",
          "仅供研究假设可借券，未核实实际融券供应")}
      </label>}
      <label>{say("Drawdown stop (%)","回撤止损（%）")}
        <input type="number" min="5" max="60" value={drawdown}
          onChange={e=>setDrawdown(e.target.value)}/></label>
      <button type="button" disabled={busy} onClick={start}>
        {say("Start forward paper from this selection","按当前选定策略启动前向模拟")}
      </button>
    </div>}
    {sourceJobId&&<p className="pf-disclaimer">
      {say("Broker pricing is an editable assumption dated Nov 18, 2026. A USD-funded account is modeled after any upfront CAD-to-USD conversion. FX and stock-loan quotes are not executable prices. A next-session open after a 4 pm ET signal is normally more than 12 hours later.",
        "券商定价为2026年11月18日的可编辑假设。加元本金先按假设成本转换为美元，再进行模拟交易。汇率与融券价格不是可执行报价。美东时间下午4点后的下一交易日开盘通常超过12小时。")}
    </p>}
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
      <p>{say("Broker cost model","券商成本模型")}: {selected.broker.broker} ·
        {selected.broker.account_type} · {selected.broker.pricing_date} ·
        {selected.capital_currency} {say("funded","入金")} ·
        {say("Initial FX fee","初始换汇费用")}: {display(selected.fx_conversion_fee_usd)} USD
        {selected.fx_rate!=null&&<> · USD/CAD {display(selected.fx_rate)}</>}
      </p>
      <p className="pf-disclaimer">
        {say("Execution:","模拟执行：")} {selected.execution_profile.fill_timing} ·
        {say("Slippage:","滑点：")} {display(selected.execution_profile.slippage_bps)} bps ·
        {say("Margin rate:","融资年利率：")} {display(selected.execution_profile.margin_rate_pct,"%")} ·
        {say("Borrow rate:","融券年利率：")} {display(selected.execution_profile.short_borrow_rate_pct,"%")} ·
        {say("Borrow policy:","融券假设：")} {selected.execution_profile.borrow_policy}
      </p>
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
        <div><small>{say("Trade commissions (USD)","交易佣金（美元）")}</small>
          <strong>{display(selected.transaction_fees_paid)} USD</strong></div>
        {selected.equity_cad!=null&&<div><small>{say("CAD marked portfolio value","加元市值")}</small>
          <strong>{display(selected.equity_cad)} CAD</strong></div>}
        {selected.paper_pnl_cad!=null&&<div><small>{say("Net CAD P&L including FX","含换汇费用加元盈亏")}</small>
          <strong>{display(selected.paper_pnl_cad)} CAD</strong></div>}
        {selected.current_drawdown_cad_pct!=null&&<div>
          <small>{say("CAD drawdown from peak","加元峰值回撤")}</small>
          <strong>{display(selected.current_drawdown_cad_pct,"%")}</strong></div>}
      </div>
      <h5>{say("New-session comparison with frozen equal-weight benchmark",
        "新交易日与冻结等权基准比较")}</h5>
      {selected.forward_benchmark.status==="available"?<>
        <div className="pf-metrics">
          <div><small>{say("Exact-date equal-weight return (price only)",
            "同日期等权收益（仅价格）")}</small>
            <strong>{display(selected.forward_benchmark.return_pct,"%")}</strong></div>
          <div><small>{say("Strategy minus equal weight (percentage points)",
            "策略相对等权收益（百分点）")}</small>
            <strong>{display(selected.forward_benchmark.strategy_minus_benchmark_return_pct_points," pp")}</strong></div>
        </div>
        <p className="pf-disclaimer">{say(
          "The dotted line is a price-only, zero-fee buy-and-hold benchmark frozen at the study activation close. It uses only the exact subsequent sessions recorded by this paper study; no dividend reinvestment, trade latency, or borrow costs. Green is the simulated strategy. Historical audit performance does not alter either series.",
          "虚线为研究启动日收盘时冻结的零费用、仅价格等权持有基准，只使用该研究随后真实记录的相同交易日。未计股息再投资、成交延迟与借券费用。绿色是策略模拟净值；历史审计结果不改变这两条曲线。")}</p>
      </>:<p>{say("This study predates benchmark tracking. The missing forward baseline cannot be reconstructed as an originally frozen benchmark.",
        "本研究建立于基准跟踪功能之前，无法事后将历史价格伪装为当时已冻结的基准。")}</p>}
      {selected.frozen_strategy_fingerprint&&<p className="pf-disclaimer">
        {say("Frozen research identity","冻结研究身份")}: <code>{selected.frozen_strategy_fingerprint.slice(0,16)}</code>
      </p>}
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
      <EquityChart marks={selected.marks}
        label={say("Observed forward-paper equity, USD","观察到的前向模拟净值（美元）")}/>
      {selected.statistics_cad&&<p>
        {say("Annualized CAD return","加元年化收益")}: {display(selected.statistics_cad.cagr_pct,"%")} ·
        {say("CAD excess Sharpe","加元超额夏普")}: {display(selected.statistics_cad.excess_sharpe)}
      </p>}
      <div className="pf-scroll"><table><thead><tr>
        <th>{say("Session","日期")}</th><th>{say("Equity USD","净值（美元）")}</th>
        <th>{say("Equal-weight USD","等权基准（美元）")}</th>
        <th>{say("Drawdown","回撤")}</th><th>{say("Gross exposure","总敞口")}</th>
      </tr></thead><tbody>{selected.marks.slice(-40).reverse().map(item=><tr key={item.session}>
        <td>{item.session}</td><td>{display(item.value)} USD</td>
        <td>{display(item.benchmark_value)} USD</td>
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
