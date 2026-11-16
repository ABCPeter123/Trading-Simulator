import { useI18n } from "./i18n";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft, ArrowUpRight, ArrowDownRight, BarChart3, Bot, Check,
  ChevronRight, Clock3, FastForward, Pause, Play, Plus, Save,
  Search, ShieldCheck, ShoppingCart, Trash2, Wallet,
} from "lucide-react";
import { PriceChart } from "./components/PriceChart";
import StrategyAnalytics from "./StrategyAnalytics";
import type { StrategyExecution } from "./strategyAnalyticsApi";
import { ASSETS, formatMoney, formatPrice } from "./data/demoMarket";
import { gameCatalog, gameDiscover, gameImportTicker } from "./arcadeApi";
import type { CatalogInstrument, DiscoveredInstrument } from "./arcadeApi";
import type { Asset, TradeSide } from "./types";
import {
  listPortfolioSeasons, loadPortfolioSeason, newPortfolioSeason,
  advancePortfolio, tradePortfolio, cancelPortfolioOrder,
  savePortfolioStrategy, savePortfolioRisk,
} from "./portfolioApi";
import type { PortfolioSaved, PortfolioSeason } from "./portfolioApi";
import "./arcade.css";
import "./portfolio.css";

const SAVED = "trade-sim-active-portfolio-season";
const HISTORY_OPTIONS = ["1Y","2Y","5Y","10Y","MAX"];
const errorText = (e: unknown) => e instanceof Error ? e.message : "Operation failed.";
const fmtQty = (n:number) => n.toLocaleString("en-US", {maximumFractionDigits:8});
const fmtTime = (t:number) => new Date(t*1000).toLocaleDateString("en-CA");
const eligible = (i: CatalogInstrument) =>
  i.tradable && i.currency === "USD" && ["Stocks","ETFs","Crypto"].includes(i.asset_class);

export default function PortfolioArcade({onExit}: {onExit:()=>void}) {
  const {t} = useI18n();
  const [catalog, setCatalog] = useState<CatalogInstrument[]>([]);
  const [saved, setSaved] = useState<PortfolioSaved[]>([]);
  const [season, setSeason] = useState<PortfolioSeason|null>(null);
  const [setup, setSetup] = useState(true);
  const [basket, setBasket] = useState<string[]>(["spy","qqq"]);
  const [search, setSearch] = useState("");
  const [external, setExternal] = useState<DiscoveredInstrument[]>([]);
  const [searchBusy, setSearchBusy] = useState(false);
  const [period, setPeriod] = useState("5Y");
  const [startDate, setStartDate] = useState("");
  const [focused, setFocused] = useState("spy");
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const activeSeasonRef = useRef<string|null>(null);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [side, setSide] = useState<TradeSide>("buy");
  const [kind, setKind] = useState<"market"|"limit"|"stop">("market");
  const [size, setSize] = useState("25");
  const [sizeType, setSizeType] = useState<"percent"|"units">("percent");
  const [trigger, setTrigger] = useState("");
  const [source, setSource] = useState("spy");
  const [target, setTarget] = useState("qqq");
  const [strategy, setStrategy] = useState("");
  const [stop, setStop] = useState("0");
  const [take, setTake] = useState("0");
  const [chartStyle, setChartStyle] = useState<"candles"|"line">("candles");
  const [maFast, setMaFast] = useState(20);
  const [maSlow, setMaSlow] = useState(100);
  const [showSma, setShowSma] = useState(true);
  const [showCrossovers, setShowCrossovers] = useState(true);
  const [showTrades, setShowTrades] = useState(true);
  const [analyticsFills, setAnalyticsFills] = useState<{runId:string;executions:StrategyExecution[]}|null>(null);

  const selected = catalog.find(item => item.id === focused);
  const chosenAsset: Asset = useMemo(() => {
    const original = ASSETS.find(item => item.id === focused);
    if (original) return original;
    return {
      id: focused, symbol: selected?.symbol ?? focused.toUpperCase(),
      name: selected?.name ?? focused, exchange: selected?.currency ?? "USD",
      assetClass: (selected?.asset_class ?? "Stocks") as Asset["assetClass"],
      decimals: selected?.decimals ?? 2, spreadBps: 5, accent:"#aa9bff",
    };
  }, [focused, selected?.symbol, selected?.name, selected?.currency, selected?.asset_class, selected?.decimals]);

  const hydrate = useCallback((next: PortfolioSeason) => {
    const changedRun = activeSeasonRef.current !== next.id;
    activeSeasonRef.current = next.id;
    setSeason(next);
    if (changedRun) {
      setFocused(next.asset_ids[0]);
      setSource(next.asset_ids[0]);
      setTarget(next.asset_ids.at(-1)!);
      setStrategy(next.strategy);
      setStop(String(next.risk.stop_loss_pct));
      setTake(String(next.risk.take_profit_pct));
      setSaved(prev => prev.some(item=>item.id===next.id) ? prev : [
        {id:next.id,asset_ids:next.asset_ids,period:next.period,updated_at:new Date().toISOString()},...prev,
      ]);
    }
    setSetup(false);
    localStorage.setItem(SAVED, next.id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void Promise.all([gameCatalog(), listPortfolioSeasons()]).then(async ([instruments,runs]) => {
      if (cancelled) return;
      setCatalog(instruments);
      setSaved(runs);
      const preferred = localStorage.getItem(SAVED);
      const resume = runs.find(run=>run.id===preferred) ?? runs[0];
      if (resume) {
        const data = await loadPortfolioSeason(resume.id);
        if (!cancelled) hydrate(data);
      }
    }).catch(e=>{if(!cancelled)setError(errorText(e));});
    return ()=>{cancelled=true;};
  }, [hydrate]);

  const update = async (task:()=>Promise<PortfolioSeason>) => {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true); setError("");
    try {
      const next = await task();
      hydrate(next);
      setNotice(next.events[0] || "Saved.");
      if(next.finished) setPlaying(false);
    } catch(e) {
      setError(errorText(e));
      setPlaying(false);
    } finally {
      busyRef.current = false; setBusy(false);
    }
  };

  useEffect(() => {
    if (!playing || !season || season.finished || setup) return;
    const timer = setInterval(() => {
      if (busyRef.current) return;
      busyRef.current = true;
      void advancePortfolio(season.id, 5).then(next => {
        hydrate(next);
        if (next.finished) setPlaying(false);
      }).catch(e=>{setError(errorText(e));setPlaying(false);}).finally(()=>{busyRef.current=false;});
    }, 700);
    return ()=>clearInterval(timer);
  }, [playing,season?.id,season?.finished,setup,hydrate]);

  const assetName = (id:string) => catalog.find(i=>i.id===id)?.symbol ??
    ASSETS.find(i=>i.id===id)?.symbol ?? id.toUpperCase();
  const positions = season?.positions ?? [];
  const current = positions.find(p=>p.asset_id===focused);
  const bars = season?.bars[focused] ?? [];
  const last = bars.at(-1);
  const markers = (analyticsFills !== null && analyticsFills.runId === season?.id
    ? analyticsFills.executions : season?.fills ?? [])
    .filter(fill=>fill.asset_id===focused)
    .map(fill=>({time:fill.time,side:fill.side,quantity:fill.quantity,price:fill.price,source:fill.source}));
  const filtered = catalog.filter(i=>eligible(i)&&
    (i.symbol+" "+i.name).toLowerCase().includes(search.toLowerCase())).slice(0,100);
  const discover = async () => {
    setSearchBusy(true);setError("");
    try {setExternal(await gameDiscover(search));}
    catch(e){setError(errorText(e));}
    finally{setSearchBusy(false);}
  };
  const importSymbol = async (symbol: string) => {
    setSearchBusy(true);setError("");
    try {
      const newAsset = await gameImportTicker(symbol);
      setCatalog(prev=>prev.some(a=>a.id===newAsset.id)?prev:[...prev,newAsset]);
      if(!eligible(newAsset)) {
        setError(symbol+" is available for research but is not eligible for USD cash portfolio trading.");
      } else {
        setBasket(prev=>prev.includes(newAsset.id)?prev:prev.length<5?[...prev,newAsset.id]:prev);
        setNotice(symbol+" imported and saved locally.");
      }
      setExternal([]);
    } catch(e){setError(errorText(e));}
    finally{setSearchBusy(false);}
  };
  const advance = (n:number, untilAction=false) => {
    if(season) void update(()=>advancePortfolio(season.id,n,untilAction));
  };
  const addRule = () => {
    const line = `WHEN ${source} SMA(10) CROSSES ABOVE SMA(30) BUY 25% ${target}`;
    setStrategy(prev=>prev.trim()?prev.trim()+"\n"+line:line);
  };
  const trade = (e: React.FormEvent) => {
    e.preventDefault();
    if(!season)return;
    void update(()=>tradePortfolio(season.id,{
      asset_id:focused, side, kind, size, size_type:sizeType,
      ...(kind==="market"?{}:{price:trigger}),
    }));
  };

  return <div className="arc-page port-page">
    <header className="arc-top">
      <div className="arc-top-left">
        <button className="arc-back" onClick={()=>{setPlaying(false);onExit();}} aria-label="Back to single-asset Arcade"><ArrowLeft size={18}/></button>
        <div className="arc-logo"><BarChart3 size={23}/></div>
        <div className="arc-brand">{t("PORTFOLIO")} <span>{t("ARCADE")}</span><small>{t("MULTI-ASSET HISTORICAL TRADING")}</small></div>
      </div>
      <div className="arc-top-right">
        {season && <span className="arc-live"><span/> {season.day} · LVL {season.metrics.level}</span>}
        <button className="arc-outline-button" onClick={()=>{setPlaying(false);setSetup(true);}}><Plus size={15}/> {t("New basket")}</button>
      </div>
    </header>
    {setup || !season ? <main className="port-setup">
      <span className="arc-upper">{t("MULTI-ASSET CHALLENGE")}</span>
      <h1>{t("One portfolio.")} <em>{t("Multiple markets.")}</em></h1>
      <p>{t("Choose 2 to 5 instruments. All positions use a shared $100,000 USD account. Prices come from synchronized historical daily candles, with no future information revealed.")}</p>
      <div className="port-picker">
        <div className="port-selected"><strong>{t("YOUR BASKET")} ({basket.length}/5)</strong>
          <div>{basket.map(id=><button key={id} onClick={()=>setBasket(prev=>prev.filter(x=>x!==id))}>{assetName(id)} ×</button>)}</div>
        </div>
        <label htmlFor="port-search"><Search size={15}/> {t("Search instruments")}</label>
        <input id="port-search" type="search" value={search} onChange={e=>{setSearch(e.target.value);setExternal([]);}} placeholder={t("Apple, SPY, BTC ...")}/>
        <button className="port-search-more" disabled={searchBusy||search.trim().length<2} onClick={()=>void discover()}>
          {t(searchBusy?"Searching provider...":"Discover more instruments on Yahoo Finance")}
        </button>
        {external.length>0&&<div className="port-discovery">{external.map(item=><div key={item.symbol}>
          <span><strong>{item.symbol}</strong><small>{item.name} · {item.currency}</small></span>
          <button disabled={searchBusy} onClick={()=>void importSymbol(item.symbol)}>{t("Import")}</button>
        </div>)}</div>}
        <div className="port-catalog">{filtered.map(a=><button key={a.id}
          className={basket.includes(a.id)?"selected":""}
          disabled={!basket.includes(a.id)&&basket.length>=5}
          onClick={()=>setBasket(prev=>prev.includes(a.id)?prev.filter(x=>x!==a.id):[...prev,a.id])}>
          <strong>{a.symbol}</strong><small>{a.name}</small><span>{basket.includes(a.id)?t("Added"):"+"}</span>
        </button>)}</div>
        <div className="port-settings">
          <label>{t("Historical range")}<select value={period} onChange={e=>setPeriod(e.target.value)}>{HISTORY_OPTIONS.map(v=><option key={v} value={v}>{v==="MAX"?t("Maximum available"):v}</option>)}</select></label>
          <label>{t("Start date (optional)")}<input type="date" value={startDate} onChange={e=>setStartDate(e.target.value)}/></label>
        </div>
        {error&&<p className="arc-error" role="alert">{error}</p>}
        <button className="arc-cta" disabled={busy||basket.length<2}
          onClick={()=>void update(()=>newPortfolioSeason(basket,period,startDate))}>
          <Play size={16}/> {t(busy?"Loading real historical data...":"Start portfolio season")}
        </button>
        {saved.length>0 && <label>{t("Resume saved season")}<select defaultValue="" onChange={e=>{
          if(e.target.value) void update(()=>loadPortfolioSeason(e.target.value));
        }}><option value="">{t("Select a saved basket")}</option>{saved.map(x=>
          <option key={x.id} value={x.id}>{x.asset_ids.map(assetName).join(" + ")} · {x.period}</option>)}</select></label>}
      </div>
    </main> : <main className="port-layout">
      <section className="port-main">
        <div className="port-achievements">
          <strong>{t("LEVEL")} {season.metrics.level} · {season.metrics.score.toLocaleString()} {t("POINTS")}</strong>
          <span>{season.metrics.xp} XP</span>
          <div>{season.metrics.badges.map(badge=><span key={badge}>{t(badge)}</span>)}</div>
        </div>
        <div className="port-metrics">
          <div><small>{t("EQUITY")}</small><strong>{formatMoney(season.metrics.equity)}</strong></div>
          <div><small>{t("CASH")}</small><strong>{formatMoney(season.metrics.cash)}</strong></div>
          <div><small>{t("YOUR RETURN")}</small><strong className={season.metrics.return_pct>=0?"positive":"negative"}>{season.metrics.return_pct.toFixed(2)}%</strong></div>
          <div><small>{t("EQUAL-WEIGHT HOLD")}</small><strong>{season.metrics.equal_weight_hold_pct.toFixed(2)}%</strong></div>
        </div>
        <div className="port-toolbar">
          <span><Clock3 size={15}/> {season.day} · Step {season.current_step+1}/{season.total_steps}</span>
          <div><button disabled={busy||playing||season.finished} onClick={()=>advance(1)}><ChevronRight size={16}/> {t("1 day")}</button>
            <button disabled={busy||playing||season.finished} onClick={()=>advance(5)}><FastForward size={15}/> +5</button>
            <button disabled={busy||playing||season.finished} onClick={()=>advance(20)}><FastForward size={15}/> +20</button>
            <button disabled={busy||playing||season.finished||!season.strategy} onClick={()=>advance(100,true)}>{t("Next bot")}</button>
            <button disabled={busy||season.finished} onClick={()=>setPlaying(v=>!v)}>{playing?<Pause size={15}/>:<Play size={15}/>} {t(playing?"Pause":"Autoplay")}</button>
          </div>
        </div>
        <div className="port-asset-tabs">{season.asset_ids.map(id=><button key={id}
          className={id===focused?"active":""} onClick={()=>setFocused(id)}>
          <strong>{assetName(id)}</strong><span>{formatPrice(season.positions.find(p=>p.asset_id===id)?.last_price??0,2)}</span>
        </button>)}</div>
        <div className="port-chart-wrap">
          <div className="arc-box-head"><div><BarChart3 size={17}/><strong>{assetName(focused)} · {chosenAsset.name}</strong>
            <span className="arc-tag">{t("FUTURE HIDDEN")}</span></div>
            <div className="arc-chart-view"><button className={chartStyle==="candles"?"selected":""} onClick={()=>setChartStyle("candles")}>{t("Candles")}</button>
              <button className={chartStyle==="line"?"selected":""} onClick={()=>setChartStyle("line")}>{t("Line")}</button></div>
          </div>
          <div className="an-chart-controls">
            <label><input type="checkbox" checked={showSma} onChange={e=>setShowSma(e.target.checked)}/>{t("SMA overlays")}</label>
            {showSma&&<><label>{t("Fast SMA")} <select value={maFast} onChange={e=>setMaFast(Number(e.target.value))}>{[5,10,20,30,50,100,150,200].map(p=><option key={p} value={p}>{p}</option>)}</select></label>
              <label>{t("Slow SMA")} <select value={maSlow} onChange={e=>setMaSlow(Number(e.target.value))}>{[10,20,30,50,100,150,200].map(p=><option key={p} value={p}>{p}</option>)}</select></label>
              <label><input type="checkbox" checked={showCrossovers} onChange={e=>setShowCrossovers(e.target.checked)}/>{t("Crossovers")}</label></>}
            <label><input type="checkbox" checked={showTrades} onChange={e=>setShowTrades(e.target.checked)}/>{t("Trade markers")}</label>
          </div>
          <div className="arc-chart-wrap">{bars.length>0&&
            <PriceChart asset={chosenAsset} range="1Y" style={chartStyle} bars={bars} visibleWindow={110}
              smaPeriods={showSma?[maFast,maSlow]:[]} showCrossovers={showSma&&showCrossovers}
              trades={showTrades?markers:[]}/>}</div>
          <div className="an-chart-key">
            {showSma&&<><b style={{color:"#e9bb74"}}>SMA {maFast}</b><b style={{color:"#a99dff"}}>SMA {maSlow}</b></>}
            {showTrades&&<><b style={{color:"#4ad4a0"}}>{t("Buy marker")}</b><b style={{color:"#fa7c8a"}}>{t("Sell marker")}</b></>}
            {showSma&&showCrossovers&&<b>{t("SMA crossover dots")}</b>}
          </div>
          <div className="port-source">{season.sources[focused]} · {t("Last actual bar:")} {last?fmtTime(last.time):t("none")}
            {current&&!current.has_bar_today&&<span> · {t("Market closed on")} {season.day}, {t("no orders filled for this symbol")}</span>}</div>
        </div>
        <div className="port-positions">
          <div className="arc-box-head"><div><Wallet size={17}/><strong>{t("Portfolio positions")}</strong></div><span className="arc-tag">{t("SHARED USD ACCOUNT")}</span></div>
          <div className="arc-table-scroll"><table><thead><tr><th>{t("SYMBOL")}</th><th>{t("QTY")}</th><th>{t("AVG COST")}</th><th>{t("MARKET VALUE")}</th><th>{t("UNREALIZED P&L")}</th><th>{t("MARK DATE")}</th></tr></thead><tbody>
            {positions.map(p=><tr key={p.asset_id} onClick={()=>setFocused(p.asset_id)} className="port-clickrow">
              <td>{assetName(p.asset_id)}</td><td>{fmtQty(p.quantity)}</td><td>{formatMoney(p.average_cost)}</td>
              <td>{formatMoney(p.market_value)}</td><td className={(p.unrealized_pnl??0)>=0?"positive":"negative"}>{formatMoney(p.unrealized_pnl??0)}</td><td>{p.mark_day??t("None")}</td>
            </tr>)}
          </tbody></table></div>
        </div>
        <StrategyAnalytics runId={season.id} step={season.current_step} mode="portfolio" assetName={assetName}
          onReport={report=>setAnalyticsFills({runId:season.id,executions:report.executions})}/>
        <div className="port-strategy">
          <div className="arc-box-head"><div><Bot size={17}/><strong>{t("Cross-asset strategy lab")}</strong></div><span className="arc-tag">{t("SAFE RULE LANGUAGE")}</span></div>
          <p>{t("A signal from one instrument can trade another. Orders queue after the signal candle closes and fill no earlier than the target symbol's next actual session.")}</p>
          <div className="port-rule-row">
            <label>{t("Signal symbol")}<select value={source} onChange={e=>setSource(e.target.value)}>{season.asset_ids.map(id=><option key={id} value={id}>{assetName(id)}</option>)}</select></label>
            <label>{t("Trade symbol")}<select value={target} onChange={e=>setTarget(e.target.value)}>{season.asset_ids.map(id=><option key={id} value={id}>{assetName(id)}</option>)}</select></label>
            <button onClick={addRule}><Plus size={16}/> {t("Add crossover rule")}</button>
          </div>
          <textarea aria-label={t("Cross-asset strategy rules")} rows={5} spellCheck={false} value={strategy}
            onChange={e=>setStrategy(e.target.value)} placeholder="WHEN spy SMA(10) CROSSES ABOVE SMA(30) BUY 25% qqq"/>
          <div className="port-rule-row"><button onClick={()=>setStrategy(
            `WHEN ${source} SMA(10) CROSSES ABOVE SMA(30) BUY 25% ${target}\nWHEN ${source} SMA(10) CROSSES BELOW SMA(30) SELL 100% ${target}`
          )}>{t("Use crossover template")}</button>
            <button disabled={busy||playing||strategy===season.strategy} onClick={()=>void update(()=>savePortfolioStrategy(season.id,strategy))}><Save size={16}/> {t("Save & arm bot")}</button>
          </div>
        </div>
        <div className="port-history">
          <div className="arc-box-head"><div><Clock3 size={17}/><strong>{t("Trade journal")}</strong></div><span>{season.fills.length} {t("recent fills")}</span></div>
          <div className="arc-table-scroll"><table><thead><tr><th>{t("DATE")}</th><th>{t("SYMBOL")}</th><th>{t("SIDE")}</th><th>{t("QTY")}</th><th>{t("PRICE")}</th><th>{t("FEE")}</th><th>{t("ENGINE")}</th></tr></thead><tbody>
            {season.fills.slice(0,30).map((fill,i)=><tr key={fill.order_id+"-"+i}>
              <td>{fmtTime(fill.time)}</td><td>{assetName(fill.asset_id)}</td><td className={fill.side==="buy"?"positive":"negative"}>{t(fill.side.toUpperCase())}</td>
              <td>{fmtQty(fill.quantity)}</td><td>{formatMoney(fill.price)}</td><td>{formatMoney(fill.fee)}</td><td>{t(fill.source)}</td>
            </tr>)}
          </tbody></table></div>
        </div>
      </section>
      <aside className="port-side">
        <section className="port-trade">
          <div className="arc-box-head"><div><ShoppingCart size={17}/><strong>{t("Trade")} {assetName(focused)}</strong></div></div>
          <form onSubmit={trade}>
            <div className="port-toggle"><button type="button" className={side==="buy"?"active-buy":""} onClick={()=>setSide("buy")}><ArrowUpRight size={15}/> {t("Buy")}</button>
              <button type="button" className={side==="sell"?"active-sell":""} onClick={()=>setSide("sell")}><ArrowDownRight size={15}/> {t("Sell")}</button></div>
            <label>{t("Order type")}<select value={kind} onChange={e=>setKind(e.target.value as typeof kind)}>
              <option value="market">{t("Market · next available open")}</option><option value="limit">{t("Limit")}</option><option value="stop">{t("Stop")}</option>
            </select></label>
            {kind!=="market"&&<label>{t("Trigger price")}<input type="number" min="0.000001" step="any" required value={trigger} onChange={e=>setTrigger(e.target.value)}/></label>}
            <label>{t("Size type")}<select value={sizeType} onChange={e=>setSizeType(e.target.value as typeof sizeType)}><option value="percent">{t("% of cash / holdings")}</option><option value="units">{t("Exact units")}</option></select></label>
            <label>{t("Quantity")}<input type="number" min="0.00000001" step="any" required value={size} onChange={e=>setSize(e.target.value)}/></label>
            {sizeType==="percent"&&<div className="port-percent">{[10,25,50,100].map(n=><button key={n} type="button" onClick={()=>setSize(String(n))}>{n}%</button>)}</div>}
            <p>{t("Held:")} {fmtQty(current?.quantity??0)} · {t("Cash:")} {formatMoney(season.metrics.cash)}</p>
            <button className="port-submit" disabled={busy||playing||season.finished} type="submit">{t(side==="buy"?"Queue Buy":"Queue Sell")}</button>
          </form>
        </section>
        <section className="port-risk">
          <div className="arc-box-head"><div><ShieldCheck size={17}/><strong>{t("Portfolio risk controls")}</strong></div></div>
          <p>{t("Applies the same percentages to each held symbol using its own average cost.")}</p>
          <label>{t("Stop loss %")}<input type="number" value={stop} min="0" max="75" step="0.1" onChange={e=>setStop(e.target.value)}/></label>
          <label>{t("Take profit %")}<input type="number" value={take} min="0" max="75" step="0.1" onChange={e=>setTake(e.target.value)}/></label>
          <button disabled={busy||playing} onClick={()=>void update(()=>savePortfolioRisk(season.id,Number(stop),Number(take)))}><ShieldCheck size={15}/> {t("Apply risk limits")}</button>
        </section>
        <section className="port-queue">
          <div className="arc-box-head"><div><Clock3 size={17}/><strong>{t("Pending orders")}</strong></div><span>{season.orders.length}</span></div>
          {season.orders.length===0?<p>{t("No pending orders")}</p>:season.orders.map(o=><div className="port-queue-item" key={o.id}>
            <span>{assetName(o.asset_id)} {t(o.side.toUpperCase())} {o.size}{o.size_type==="percent"?"%":""} · {t(o.kind.toUpperCase())} {o.source==="bot"?t("(bot)"):""}</span>
            <button disabled={busy||playing} title={t("Cancel order")} onClick={()=>void update(()=>cancelPortfolioOrder(season.id,o.id))}><Trash2 size={15}/></button>
          </div>)}
        </section>
        {notice&&<div className="arc-note" role="status"><Check size={15}/>{t(notice)}<button onClick={()=>setNotice("")}>×</button></div>}
        {error&&<div className="arc-error" role="alert">{t(error)}</div>}
        <p className="port-disclaimer">{t(season.execution_notice)}</p>
      </aside>
    </main>}
  </div>;
}
