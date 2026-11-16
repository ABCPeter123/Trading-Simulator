import { useI18n } from "./i18n";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity, ArrowDownRight, ArrowUpRight, Bot, Check,
  ChevronLeft, ChevronRight, Clock3, Code2, FastForward, Flag, Gauge, Pause,
  Play, Plus, Save, ShieldCheck, Sparkles, Target, Terminal,
  Trash2, Wallet,
} from "lucide-react";
import { ASSETS, formatMoney, formatPrice } from "./data/demoMarket";
import type { Asset } from "./types";
import VisualStrategyBuilder from "./VisualStrategyBuilder";
import StrategyAnalytics from "./StrategyAnalytics";
import AIAssistant from "./AIAssistant";
import WorkspaceTabs from "./WorkspaceTabs";
import type { WorkspaceTab } from "./WorkspaceTabs";
import StochasticResearch from "./StochasticResearch";
import MarketDesk from "./MarketDesk";
import StrategyLibrary from "./StrategyLibrary";
import type { StrategyExecution } from "./strategyAnalyticsApi";
import { PriceChart } from "./components/PriceChart";
import { REPLAY_WINDOWS, RESOLUTIONS, aggregateBars, chartTrades as mapChartTrades, chartViewsFor, showReplayTime } from "./replayIntervals";
import type { ReplayResolution, ReplayWindow } from "./replayIntervals";
import {
  gameCancel, gameCatalog, gameDiscover, gameImportTicker, gameLoad, gameRuns, gameSaveCode, gameSetRisk, gameStart, gameStep,
  gameTrade, gameValidateCode, gameAt,
} from "./arcadeApi";
import type { ArcadeRun, CatalogInstrument, DiscoveredInstrument, OrderKind, SavedArcadeRun } from "./arcadeApi";
import type { TradeSide } from "./types";
import "./arcade.css";

const SAVED_KEY = "trading-simulator-arcade-current-run";
const QUICK_SIZES = [10, 25, 50, 100];
const asTime = (seconds: number, resolution: ReplayResolution = "1d") => showReplayTime(seconds,resolution);
const errText = (error: unknown) => error instanceof Error ? error.message : "An unexpected error occurred.";
const SAMPLE_CODE = "WHEN SMA(10) CROSSES ABOVE SMA(30) BUY 50%\nWHEN SMA(10) CROSSES BELOW SMA(30) SELL 100%";

function Metric({label, value, note, positive}: {label: string; value: string; note?: string; positive?: boolean}) {
  return <div className="arc-metric"><span>{label}</span><strong className={positive===undefined?"":positive?"positive":"negative"}>{value}</strong>{note && <small>{note}</small>}</div>;
}

export default function TradingArcade({onOpenPortfolio}: {onOpenPortfolio:()=>void}) {
  const {t} = useI18n();
  const [game, setGame] = useState<ArcadeRun|null>(null);
  const [workspaceTab,setWorkspaceTab] = useState<WorkspaceTab>("overview");
  const [saved, setSaved] = useState<SavedArcadeRun[]>([]);
  const [catalog, setCatalog] = useState<CatalogInstrument[]>([]);
  const [catalogSearch, setCatalogSearch] = useState("");
  const [remoteResults, setRemoteResults] = useState<DiscoveredInstrument[]>([]);
  const [searchingRemote, setSearchingRemote] = useState(false);
  const [importingSymbol, setImportingSymbol] = useState("");
  const [catalogClass, setCatalogClass] = useState("All");
  const [period, setPeriod] = useState<ReplayWindow>("5Y");
  const [resolution, setResolution] = useState<ReplayResolution>("1d");
  const [chartView,setChartView] = useState<ReplayResolution>("1d");
  const [stopPct, setStopPct] = useState("0");
  const [takePct, setTakePct] = useState("0");
  const [assetId, setAssetId] = useState("aapl");
  const [startingPoint, setStartingPoint] = useState(0.3);
  const [startDate, setStartDate] = useState("");
  const [newGame, setNewGame] = useState(false);
  const [initializing, setInitializing] = useState(true);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [side, setSide] = useState<TradeSide>("buy");
  const [orderKind, setOrderKind] = useState<OrderKind>("market");
  const [sizeMode, setSizeMode] = useState<"percent"|"units">("percent");
  const [size, setSize] = useState("25");
  const [price, setPrice] = useState("");
  const [code, setCode] = useState(SAMPLE_CODE);
  const [codeError, setCodeError] = useState("");
  const [validating, setValidating] = useState(false);
  const [editorOpen, setEditorOpen] = useState(true);
  const [chartStyle, setChartStyle] = useState<"candles"|"line">("candles");
  const [maFast, setMaFast] = useState(20);
  const [maSlow, setMaSlow] = useState(100);
  const [showSma, setShowSma] = useState(true);
  const [showCrossovers, setShowCrossovers] = useState(true);
  const [showTrades, setShowTrades] = useState(true);
  const [analyticsFills,setAnalyticsFills] = useState<{runId:string;executions:StrategyExecution[]}|null>(null);

  const load = useCallback(async (id: string) => {
    const run = await gameLoad(id);
    setGame(run);
    setWorkspaceTab("overview");
    setChartView(run.resolution??"1d");
    setCode(run.strategy || SAMPLE_CODE);
    setStopPct(String(run.risk?.stop_loss_pct ?? 0));
    setTakePct(String(run.risk?.take_profit_pct ?? 0));
    setNewGame(false);
    setError("");
    localStorage.setItem(SAVED_KEY, id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const boot = async () => {
      try {
        const [runs, instruments] = await Promise.all([gameRuns(), gameCatalog()]);
        if (cancelled) return;
        setSaved(runs);
        setCatalog(instruments);
        const stored = localStorage.getItem(SAVED_KEY);
        const resume = runs.find(r=>r.id===stored) ?? runs[0];
        if (resume) {
          try {
            const state = await gameLoad(resume.id);
            if (!cancelled) {setGame(state);setCode(state.strategy || SAMPLE_CODE);setStopPct(String(state.risk?.stop_loss_pct ?? 0));setTakePct(String(state.risk?.take_profit_pct ?? 0));localStorage.setItem(SAVED_KEY,resume.id);}
          } catch {
            if (!cancelled) setNewGame(true);
          }
        } else setNewGame(true);
      } catch(e) {
        if (!cancelled) {setNewGame(true); setError(errText(e));}
      } finally {
        if (!cancelled) setInitializing(false);
      }
    };
    void boot();
    return () => {cancelled=true;};
  }, []);

  async function action(fn:()=>Promise<ArcadeRun>, message?:string) {
    if (busyRef.current) return;
    busyRef.current=true;
    setBusy(true);
    setError("");
    try {
      const state = await fn();
      setGame(state);
      if (message) setNote(message);
      else if (state.events[0]) setNote(state.events[0]);
      if (state.finished) setPlaying(false);
    } catch(e) {
      setError(errText(e));
      setPlaying(false);
    } finally {
      busyRef.current=false;
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!playing || !game || game.finished || newGame) return;
    const runId=game.id;
    const timer = setInterval(() => {
      if (busyRef.current) return;
      busyRef.current=true;
      void gameStep(runId,speed).then(next => {
        setGame(next);
        if(next.finished) setPlaying(false);
      }).catch(e => {setError(errText(e));setPlaying(false);}).finally(() => {busyRef.current=false;});
    },650);
    return()=>clearInterval(timer);
  },[playing,game?.id,game?.finished,newGame,speed]);

  async function searchMore() {
    if(catalogSearch.trim().length<2) {setError("Enter at least two characters to search external tickers.");return;}
    setSearchingRemote(true);setError("");setRemoteResults([]);
    try {setRemoteResults(await gameDiscover(catalogSearch.trim()));}
    catch(e) {setError(errText(e));}
    finally {setSearchingRemote(false);}
  }
  async function importTicker(symbol: string) {
    setImportingSymbol(symbol);setError("");
    try {
      const item=await gameImportTicker(symbol);
      setCatalog(prev=>prev.some(p=>p.id===item.id)?prev:[...prev,item]);
      setCatalogSearch("");
      setCatalogClass("All");
      setRemoteResults([]);
      if(item.tradable&&item.currency==="USD") {
        setAssetId(item.id);
        setNote(symbol+" added to your local instruments.");
      } else {
        setNote(symbol+" imported for research, but is chart-only until currency and contract rules are supported.");
      }
    } catch(e) {setError(errText(e));}
    finally {setImportingSymbol("");}
  }

  async function createNew() {
    setPlaying(false);
    if(busyRef.current)return;
    busyRef.current=true;setBusy(true);setError("");
    try {
      const selected = filteredCatalog.find(a=>a.id===assetId) ?? filteredCatalog[0];
      if (!selected) throw Error("Choose a supported instrument.");
      const result=await gameStart(selected.id,startingPoint,period,startDate,resolution);
      setGame(result);
      setWorkspaceTab("overview");
      setChartView(result.resolution??"1d");
      setCode(SAMPLE_CODE);
      setStopPct("0");
      setTakePct("0");
      setCodeError("");
      setNewGame(false);
      setSaved(await gameRuns());
      localStorage.setItem(SAVED_KEY,result.id);
      setNote("New season started. The market will reveal one candle at a time.");
    } catch(e) {setError(errText(e));}
    finally {busyRef.current=false;setBusy(false);}
  }

  async function switchRun(id: string) {
    setPlaying(false);
    setInitializing(true);
    try {await load(id);} catch(e){setError(errText(e));}
    finally {setInitializing(false);}
  }

  async function placeOrder(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if(!game)return;
    const amount=Number(size);
    if(!Number.isFinite(amount)||amount<=0||(sizeMode==="percent"&&amount>100)){
      setError("Choose a positive amount. Percentage orders must be 100% or less.");
      return;
    }
    if(orderKind!=="market"&&(!Number.isFinite(Number(price))||Number(price)<=0)){
      setError("Enter a positive limit or stop trigger price.");
      return;
    }
    setPlaying(false);
    await action(()=>gameTrade(game.id,{side,kind:orderKind,size,size_type:sizeMode,...(orderKind==="market"?{}:{price})}),
      "Order queued. Advance the timeline to execute against future candles.");
  }

  async function saveCode() {
    if(!game)return;
    setPlaying(false);
    setCodeError("");
    try {
      setValidating(true);
      const result=await gameValidateCode(code);
      if(!result.valid)throw Error("Strategy was not accepted.");
      await action(()=>gameSaveCode(game.id,code),`Bot updated with ${result.rules.length} rule(s).`);
    } catch(e){setCodeError(errText(e));}
    finally{setValidating(false);}
  }

  const filteredCatalog = catalog.filter(item => item.tradable && item.currency === "USD" &&
    (catalogClass === "All" || item.asset_class === catalogClass) &&
    (item.symbol+" "+item.name).toLowerCase().includes(catalogSearch.trim().toLowerCase()));
  const asset: Asset | undefined = useMemo(()=>{
    const original = ASSETS.find(a=>a.id===game?.asset_id);
    if (original) return original;
    const imported = catalog.find(a=>a.id===game?.asset_id);
    return imported ? {id:imported.id,symbol:imported.symbol,name:imported.name,
      exchange:imported.currency,assetClass:imported.asset_class as Asset["assetClass"],
      decimals:imported.decimals,spreadBps:5,accent:"#a7a2ff"} : undefined;
  },[game?.asset_id,catalog]);
  const viewingPast=!!game?.viewing_past;
  const latest=game?.bars.at(-1);
  const q=game?.metrics;
  const delta=latest&&game&&game.bars.length>=2 ? latest.close-game.bars[game.bars.length-2].close : 0;
  const baseResolution=game?.resolution??"1d";
  const activeChartView=chartViewsFor(baseResolution).includes(chartView)?chartView:baseResolution;
  const displayedBars=useMemo(
    ()=>aggregateBars(game?.bars??[],activeChartView),
    [game?.bars,activeChartView]
  );
  const codeSaved=game?.strategy===code;
  const chartTrades = (analyticsFills !== null && analyticsFills.runId===game?.id?analyticsFills.executions:game?.fills??[])
    .map(fill=>({time:fill.time,side:fill.side,quantity:fill.quantity,price:fill.price,source:fill.source}));

  return <div className="arc-page">
    <header className="arc-top">
      <div className="arc-top-left">
        
        <div className="arc-logo"><Activity size={23}/></div>
        <div className="arc-brand">{t("Trading")} <span>{t("Simulator")}</span><small>{t("Market research workspace")}</small></div>
      </div>
      <div className="arc-top-right">
        <span className="arc-live"><span/> {t("Historical market simulation")}</span>
        <button className="arc-outline-button" onClick={()=>{setPlaying(false);setWorkspaceTab("market");}}>{t("Market Data & Paper")}</button>
        <button className="arc-outline-button" onClick={()=>{setPlaying(false);onOpenPortfolio();}}><Wallet size={15}/> {t("Portfolio Simulator")}</button>

        <button className="arc-outline-button" onClick={()=>{setPlaying(false);setWorkspaceTab("overview");setNewGame(true);setError("");}}><Plus size={15}/> {t("New session")}</button>
      </div>
    </header>

    {initializing ? <div className="arc-intro"><Activity className="spin" size={30}/><h2>{t("Loading historical sessions")}</h2><p>{t("Loading saved simulation sessions.")}</p></div> :
     workspaceTab==="market" ? <main className="arc-layout" data-tab="market">
       <WorkspaceTabs active={workspaceTab} onChange={setWorkspaceTab}/>
       <MarketDesk/>
     </main> :
     newGame || !game ? <main className="arc-intro">
       <div className="arc-intro-icon"><Activity size={35}/></div>
       <span className="arc-upper">{t("HISTORICAL MARKET RESEARCH")}</span>
       <h1>{t("Trading Simulator")}</h1>
       <p>{t("Start with $100,000 in simulated capital. Analyze real historical candles, test rule-based strategies, and compare performance with a benchmark.")}</p>
       <button type="button" className="arc-outline-button" onClick={()=>setWorkspaceTab("market")}>{t("Open market data and paper account")}</button>
       <div className="arc-start-form">
         <label htmlFor="arc-market-search">Find a market · {catalog.length} {t("instruments indexed")}</label>
         <input id="arc-market-search" type="search" value={catalogSearch} placeholder={t("Search symbol or company...")} onChange={e=>{setCatalogSearch(e.target.value);setRemoteResults([]);}}/>
         <button className="arc-discover" type="button" disabled={searchingRemote||catalogSearch.trim().length<2} onClick={()=>void searchMore()}>{t(searchingRemote?"Searching Yahoo Finance...":"Find more instruments across Yahoo Finance")}</button>
         {remoteResults.length>0&&<div className="arc-remote-results">
           <strong>DISCOVERED · {remoteResults.length} RESULTS</strong>
           {remoteResults.map(item=><div key={item.symbol}>
             <span><b>{item.symbol}</b><small>{item.name} · {t(item.asset_class)} · {item.currency}</small></span>
             <button type="button" disabled={!!importingSymbol} onClick={()=>void importTicker(item.symbol)}>{t(importingSymbol===item.symbol?"Importing...":"Add")}</button>
           </div>)}
         </div>}
         <select aria-label={t("Filter asset class")} value={catalogClass} onChange={e=>setCatalogClass(e.target.value)}>
           {["All","Stocks","ETFs","Crypto","Forex"].map(group=><option key={group}>{group}</option>)}
         </select>
         <label htmlFor="arc-new-asset">Choose your market · {filteredCatalog.length} {t("matches")}</label>
         <select id="arc-new-asset" value={filteredCatalog.some(a=>a.id===assetId)?assetId:(filteredCatalog[0]?.id??"")} onChange={e=>setAssetId(e.target.value)}>
           {filteredCatalog.map(a=><option key={a.id} value={a.id}>{a.symbol} · {a.name}</option>)}
         </select>
         <label htmlFor="arc-resolution">{t("Replay candle interval")}</label>
         <select id="arc-resolution" value={resolution} onChange={e=>{
           const next=e.target.value as ReplayResolution;
           setResolution(next);setPeriod(REPLAY_WINDOWS[next][0]);setStartDate("");
         }}>
           {RESOLUTIONS.map(i=><option key={i} value={i}>{i}</option>)}
         </select>
         <label htmlFor="arc-historical-range">{t("Historical depth")}</label>
         <select id="arc-historical-range" value={period} onChange={e=>setPeriod(e.target.value as ReplayWindow)}>
           {REPLAY_WINDOWS[resolution].map(w=><option key={w} value={w}>{w==="MAX"?t("Maximum available history"):w}</option>)}
         </select>
         <small className="arc-date-hint">{t("Intraday providers have limited historical coverage. Daily bars support longer backtests; missing minute prices are never manufactured.")}</small>
         <label htmlFor="arc-choose-date">{t("Historical start date (optional)")}</label>
         <input id="arc-choose-date" type="date" value={startDate} onChange={e=>setStartDate(e.target.value)} title={t("Choose the replay start date. Leave blank to use the configured starting point.")}/>
         <small className="arc-date-hint">{t("Choose a date such as 2008-09-15 or 2020-03-01. Requires source coverage and indicator warmup.")}</small>
         <label htmlFor="arc-start-point">{t("Starting point")} {startDate?t("(ignored when date is set)"):""}</label>
         <select id="arc-start-point" value={startingPoint} onChange={e=>setStartingPoint(Number(e.target.value))}>
           <option value={0.2}>{t("Long replay · More history")}</option>
           <option value={0.3}>{t("Standard replay")}</option>
           <option value={0.5}>{t("Short replay")}</option>
         </select>
         <button disabled={busy} className="arc-cta" onClick={()=>void createNew()}><Play size={18} fill="currentColor"/>{t(busy?"Loading market data...":"Start trading")}</button>
         {saved.length>0 && <><span className="arc-resume-title">{t("RESUME PREVIOUS SESSION")}</span><select aria-label={t("Resume a saved simulation")} defaultValue="" onChange={e=>{if(e.target.value)void switchRun(e.target.value);}}><option value="">{t("Select a previous run...")}</option>{saved.map(run=><option key={run.id} value={run.id}>{ASSETS.find(a=>a.id===run.asset_id)?.symbol} · {new Date(run.updated_at).toLocaleString()}</option>)}</select></>}
         {error && <div className="arc-error" role="alert">{error}</div>}
       </div>
       <div className="arc-intro-foot"><ShieldCheck size={15}/> {t("Uses actual historical candles when available. All trading is simulated.")}</div>
     </main> : <main className="arc-layout" data-tab={workspaceTab}>
       <WorkspaceTabs active={workspaceTab} onChange={setWorkspaceTab}/>
       <div className="arc-main">
         <section className="arc-hero">
           <div className="arc-symbol-line">
             <div><span className="arc-upper">{t("REPLAY IN PROGRESS")}</span><h1>{asset?.symbol??game.asset_id}<span className="arc-symbol-currency"> {t("/ USD")}</span></h1><p>{asset?.name} · {game.period} / {baseResolution} · {game.source}</p></div>
             <div className="arc-price"><strong>{latest ? formatPrice(latest.close,asset?.decimals??2):"—"}</strong><span className={delta>=0?"positive":"negative"}>{delta>=0?<ArrowUpRight size={15}/>:<ArrowDownRight size={15}/>} {delta>=0?"+":""}{formatPrice(delta,asset?.decimals??2)} {t("last candle")}</span></div>
           </div>
           <div className="arc-progress-line">
             <div><span><Clock3 size={13}/> {latest?asTime(latest.time,baseResolution):"—"}</span><span>{game.current_bar+1} / {game.total_bars} {t("candles revealed")}</span><span>{game.progress_pct.toFixed(1)}% {t("complete")}</span></div>
             <div className="arc-progress"><div style={{width:`${game.progress_pct}%`}}/></div>
           </div>
         </section>

         <div className="arc-stat-grid">
           <Metric label="PORTFOLIO VALUE" value={formatMoney(q!.equity)} note="Marked at latest close"/>
           <Metric label="YOUR RETURN" value={`${q!.return_pct>=0?"+":""}${q!.return_pct.toFixed(2)}%`} note="After simulated fees" positive={q!.return_pct>=0}/>
           <Metric label="BUY & HOLD" value={`${q!.buy_hold_pct>=0?"+":""}${q!.buy_hold_pct.toFixed(2)}%`} note="Same market and start date" positive={q!.buy_hold_pct>=0}/>
           <Metric label="AVAILABLE CASH" value={formatMoney(q!.cash)} note="USD trading balance"/>
         </div>

         <section className="arc-chart-box">
           <div className="arc-box-head"><div><Activity size={17}/><strong>{t("Historical market")}</strong><span className="arc-tag">{t("FUTURE HIDDEN")}</span></div><div className="arc-chart-view"><button className={chartStyle==="candles"?"selected":""} onClick={()=>setChartStyle("candles")}>{t("Candles")}</button><button className={chartStyle==="line"?"selected":""} onClick={()=>setChartStyle("line")}>{t("Line")}</button></div></div>
           <div className="an-chart-controls">
             <label><input type="checkbox" checked={showSma} onChange={e=>setShowSma(e.target.checked)}/>{t("SMA overlays")}</label>
             {showSma&&<><label>{t("Fast SMA")} <select value={maFast} onChange={e=>setMaFast(Number(e.target.value))}>{[5,10,20,30,50,100,150,200].map(p=><option key={p} value={p}>{p}</option>)}</select></label>
               <label>{t("Slow SMA")} <select value={maSlow} onChange={e=>setMaSlow(Number(e.target.value))}>{[10,20,30,50,100,150,200].map(p=><option key={p} value={p}>{p}</option>)}</select></label>
               <label><input type="checkbox" checked={showCrossovers} onChange={e=>setShowCrossovers(e.target.checked)}/>{t("Crossovers")}</label></>}
             <label><input type="checkbox" checked={showTrades} onChange={e=>setShowTrades(e.target.checked)}/>{t("Trade markers")}</label>
           </div>
           <div className="an-chart-controls">
             <label>{t("Chart interval")}
               <select value={activeChartView} onChange={e=>setChartView(e.target.value as ReplayResolution)}>
                 {chartViewsFor(baseResolution).map(i=><option key={i} value={i}>{i}</option>)}
               </select>
             </label>
             <span className="an-interval-warning">{t("Signals and fills use replay resolution, not the aggregated chart view.")}</span>
           </div>
           <div className="arc-chart-wrap"><PriceChart asset={asset!} range="1Y" style={chartStyle} bars={displayedBars} visibleWindow={120}
             smaPeriods={showSma?[maFast,maSlow]:[]} showCrossovers={showSma&&showCrossovers}
             trades={showTrades?mapChartTrades(chartTrades,activeChartView):[]}/></div>
           <div className="an-chart-key">
             {showSma&&<><b style={{color:"#e9bb74"}}>SMA {maFast}</b><b style={{color:"#a99dff"}}>SMA {maSlow}</b></>}
             {showTrades&&<><b style={{color:"#4ad4a0"}}>{t("Buy marker")}</b><b style={{color:"#fa7c8a"}}>{t("Sell marker")}</b></>}
             {showSma&&showCrossovers&&<b>{t("SMA crossover dots")}</b>}
           </div>
           <div className="arc-chart-bottom"><span><span className="arc-green-dot"/> {t("REAL HISTORICAL OHLCV")}</span><span>{t("Next candle cannot be viewed until you advance")}</span></div>
         </section>

         <section className="arc-time-panel">
           <div className="arc-box-head"><div><FastForward size={17}/><strong>{t("Replay timeline")}</strong><span className="arc-tag">{t("Deterministic replay")}</span></div>{game.finished&&<span className="arc-complete"><Flag size={14}/> {t("REPLAY COMPLETE")}</span>}</div>
           <p>{t("Every step advances the historical market, checks your pending orders, and executes active strategy rules. No real-time waiting.")}</p>
           
           <div className="ts-time-actions">
             <button type="button" disabled={busy||playing||game.current_bar<=game.history_start}
               onClick={()=>void action(()=>gameAt(game.id,game.current_bar-1))}><ChevronLeft size={15}/>{t("Previous step")}</button>
             <button type="button" disabled={busy||playing||game.current_bar>=game.live_index}
               onClick={()=>void action(()=>gameAt(game.id,game.current_bar+1))}><ChevronRight size={15}/>{t("Next recorded step")}</button>
             {viewingPast&&<button type="button" onClick={()=>void action(()=>gameLoad(game.id))}>{t("Return to latest")}</button>}
             <span className={viewingPast?"ts-past-note":""}>{viewingPast?t("Historical inspection: read-only. Your latest trades are unchanged."):t("Checkpoint history is saved as the simulation advances.")}</span>
           </div>
           <div className="arc-time-actions">
             <button disabled={busy||playing||game.finished||viewingPast} onClick={()=>void action(()=>gameStep(game.id,1))}><ChevronRight size={17}/> {t("Next candle")}</button>
             <button disabled={busy||playing||game.finished||viewingPast} onClick={()=>void action(()=>gameStep(game.id,5))}><FastForward size={15}/> {t("+5 candles")}</button>
             <button disabled={busy||playing||game.finished||viewingPast} onClick={()=>void action(()=>gameStep(game.id,20))}><FastForward size={16}/> {t("+20 candles")}</button>
             <button disabled={busy||playing||game.finished||viewingPast} onClick={()=>void action(()=>gameStep(game.id,100))}><FastForward size={16}/> {t("+100 candles")}</button>
             <button disabled={busy||playing||game.finished||viewingPast||!game.strategy.trim()} onClick={()=>void action(()=>gameStep(game.id,100,true))}><Target size={16}/> {t("Next strategy signal")}</button>
           </div>
           <div className="arc-auto">
             <div><strong><Gauge size={16}/> {t("Autoplay")}</strong><span>{t("Advance observed historical bars automatically.")}</span></div>
             <select aria-label={t("Autoplay step speed")} value={speed} onChange={e=>setSpeed(Number(e.target.value))}><option value={1}>{t("1 bar / tick")}</option><option value={5}>{t("5 bars / tick")}</option><option value={10}>{t("10 bars / tick")}</option><option value={25}>{t("25 bars / tick")}</option><option value={50}>{t("50 bars / tick")}</option></select>
             <button className={playing?"arc-playing":""} disabled={game.finished||viewingPast} onClick={()=>setPlaying(p=>!p)}>{playing?<><Pause size={15}/> {t("Pause")}</>:<><Play size={15}/> {t("Run")}</>}</button>
           </div>
         </section>

         <div className="ts-analysis-panel"><StrategyAnalytics runId={game.id} step={game.current_bar} mode="single" atIndex={viewingPast?game.current_bar:undefined}
           assetName={id=>id===game.asset_id?(asset?.symbol??id.toUpperCase()):id.toUpperCase()}
           onReport={report=>setAnalyticsFills({runId:game.id,executions:report.executions})}/></div>
         <div className="ts-research-panel">
           {workspaceTab==="scenarios"&&<StochasticResearch mode="single" runId={game.id} assetIds={[game.asset_id]}
             step={game.current_bar} viewingPast={viewingPast}
             onStrategy={draft=>{setCode(draft);setEditorOpen(true);setCodeError("");setWorkspaceTab("strategy");}}/>}
         </div>
         {!viewingPast?<AIAssistant key={game.id} mode="single" runId={game.id}
           onDraft={draft=>{setCode(draft);setEditorOpen(true);setCodeError("");setWorkspaceTab("strategy");}}/>
           :<p className="ts-past-note">{t("AI research uses the latest session. Return to latest to ask questions.")}</p>}
         <section className="arc-bot-section">
           <div className="arc-box-head"><div><Bot size={18}/><strong>{t("Strategy Editor")}</strong><span className="arc-tag">{t("VALIDATED STRATEGY DSL")}</span></div><button className="arc-subtle-button" onClick={()=>setEditorOpen(v=>!v)}>{t(editorOpen?"Collapse":"Expand")}</button></div>
           <div className="arc-bot-summary"><div className="arc-bot-icon"><Code2 size={21}/></div><div><strong>{t("Define algorithmic trading rules")}</strong><p>{t("Write safe deterministic strategy rules. Signals evaluate on revealed candle closes, and orders enter the next available trading candle.")}</p></div></div>
           {editorOpen&&<div className="arc-editor">
             <VisualStrategyBuilder onAdd={rule=>{setCode(prev=>prev.trim()?prev.trim()+"\n"+rule:rule);setCodeError("");}}/>
             <div className="arc-template-row"><span>{t("TRY A TEMPLATE")}</span>{game.examples.map(sample=><button key={sample.title} onClick={()=>{setCode(sample.code);setCodeError("");}}>{t(sample.title)}</button>)}</div>
             <div className="arc-code-head"><span><Terminal size={14}/> strategy.tradesim</span><span>{t(codeSaved?"SAVED TO SESSION":"UNSAVED CHANGES")}</span></div>
             <textarea spellCheck={false} aria-label={t("Trading strategy rules")} value={code} onChange={e=>{setCode(e.target.value);setCodeError("");}} rows={5} placeholder="WHEN SMA(10) CROSSES ABOVE SMA(30) BUY 25%" maxLength={1800}/>
             <div className="arc-editor-help">
               <strong>{t("Language cheatsheet")}</strong>
               <p><code>WHEN SMA(10) CROSSES ABOVE SMA(30) BUY 25%</code> · <code>WHEN RSI(14) BELOW 30 BUY 25%</code></p>
               <p>{t("Indicators: PRICE, SMA(2-100), RSI(2-100). Conditions: ABOVE, BELOW, CROSSES ABOVE, CROSSES BELOW. Trades: BUY or SELL a percentage.")}</p>
               <p>{t("BUY % uses available cash. SELL % uses holdings. Rules trigger on crossing events, not every candle. No Python code or unsafe execution.")}</p>
             </div>
             {codeError&&<div role="alert" className="arc-error">{codeError}</div>}
             <div className="arc-code-actions"><span>{t(game.strategy.trim()?"Bot armed":"No active strategy")}</span><button disabled={busy||validating||codeSaved||viewingPast} onClick={()=>void saveCode()}><Save size={15}/>{t(validating?"Validating...":"Save & activate strategy")}</button></div>
           </div>}
         </section>
         <StrategyLibrary mode="single" runId={game.id} symbols={[game.asset_id]}
           code={code} activatedCode={game.strategy}
           onLoad={draft=>{setCode(draft);setCodeError("");setEditorOpen(true);setWorkspaceTab("strategy");}}/>

         <section className="arc-history">
           <div className="arc-box-head"><div><Clock3 size={17}/><strong>{t("Trade journal")}</strong><span className="arc-tag">{game.fills.length} {t("RECENT FILLS")}</span></div></div>
           {game.fills.length?<div className="arc-table-scroll"><table><thead><tr><th>{t("DATE")}</th><th>{t("SIDE")}</th><th>{t("TYPE")}</th><th>{t("QTY")}</th><th>{t("PRICE")}</th><th>{t("FEE")}</th></tr></thead><tbody>{game.fills.slice(0,20).map((fill,index)=><tr key={fill.order_id+"-"+index}><td>{asTime(fill.time,baseResolution)}</td><td className={fill.side==="buy"?"positive":"negative"}>{t(fill.side.toUpperCase())}</td><td>{fill.source==="bot"?t("AUTOMATED · "):""}{t(fill.kind.toUpperCase())}</td><td>{fill.quantity.toLocaleString("en-US",{maximumFractionDigits:8})}</td><td>{formatPrice(fill.price,asset?.decimals??2)}</td><td>{formatMoney(fill.fee)}</td></tr>)}</tbody></table></div>
             : <div className="arc-empty">{t("No fills yet. Place a trade, then advance the timeline.")}</div>}
         </section>
       </div>

       <aside className="arc-side">
         <section className="arc-trade-card">
           <div className="arc-box-head"><div><Wallet size={17}/><strong>{t("Trade desk")}</strong></div><span className="arc-tag">{t("PAPER MONEY")}</span></div>
           <div className="arc-side-body">
             <div className="arc-side-toggle"><button className={side==="buy"?"active-buy":""} onClick={()=>setSide("buy")}><ArrowUpRight size={16}/> {t("Buy")}</button><button className={side==="sell"?"active-sell":""} onClick={()=>setSide("sell")}><ArrowDownRight size={16}/> {t("Sell")}</button></div>
             <form onSubmit={e=>void placeOrder(e)}>
               <label htmlFor="arc-order-kind">{t("Order type")}</label>
               <select id="arc-order-kind" value={orderKind} onChange={e=>setOrderKind(e.target.value as OrderKind)}>
                 <option value="market">{t("Market · next open")}</option><option value="limit">{t("Limit · favorable price")}</option><option value="stop">{t("Stop · triggered price")}</option>
               </select>
               {orderKind!=="market"&&<><label htmlFor="arc-trigger">{t("Trigger price (USD)")}</label><input id="arc-trigger" inputMode="decimal" type="number" step="any" min="0.000001" value={price} onChange={e=>setPrice(e.target.value)} required placeholder={latest?.close.toFixed(asset?.decimals??2)}/></>}
               <div className="arc-field-row"><label htmlFor="arc-size">{t("Position size")}</label><select aria-label={t("Amount type")} value={sizeMode} onChange={e=>{setSizeMode(e.target.value as "percent"|"units");setSize("25");}}><option value="percent">{t("Percent")}</option><option value="units">{t("Units")}</option></select></div>
               <div className="arc-size-wrap"><input id="arc-size" type="number" min="0.00000001" step="any" value={size} onChange={e=>setSize(e.target.value)} required/><span>{sizeMode==="percent"?"%":"UNITS"}</span></div>
               {sizeMode==="percent"&&<div className="arc-size-presets">{QUICK_SIZES.map(n=><button type="button" key={n} className={Number(size)===n?"chosen":""} onClick={()=>setSize(String(n))}>{n}%</button>)}</div>}
               <div className="arc-quote-mini"><span>{t("Last candle close")}</span><strong>{latest?formatPrice(latest.close,asset?.decimals??2):"—"}</strong></div>
               <div className="arc-quote-mini"><span>{t("Units held")}</span><strong>{q!.quantity.toLocaleString("en-US",{maximumFractionDigits:8})}</strong></div>
               <div className="arc-quote-mini"><span>{t("Cash available")}</span><strong>{formatMoney(q!.cash)}</strong></div>
               <button className={side==="buy"?"arc-buy-cta":"arc-sell-cta"} disabled={busy||playing||game.finished||viewingPast} type="submit">{side==="buy"?<ArrowUpRight size={17}/>:<ArrowDownRight size={17}/>} Queue {t(side.toUpperCase())} {t("order")}</button>
             </form>
             <div className="arc-disclaimer"><ShieldCheck size={14}/><span>{t("Orders execute only as new candles reveal. Fees, spread and slippage are modeled.")}</span></div>
           </div>
         </section>

         <section className="arc-risk-card">
           <div className="arc-box-head"><div><ShieldCheck size={17}/><strong>{t("Protect your position")}</strong></div><span className="arc-tag">{t("AUTO EXITS")}</span></div>
           <div className="arc-risk-body">
             <p>{t("Attach automatic downside and upside exits to your holdings. Protections start on the next candle, not inside a new fill candle.")}</p>
             <div className="arc-risk-grid">
               <label>Stop loss %
                 <input type="number" min="0" max="75" step="0.1" value={stopPct} onChange={e=>setStopPct(e.target.value)}/>
               </label>
               <label>Take profit %
                 <input type="number" min="0" max="75" step="0.1" value={takePct} onChange={e=>setTakePct(e.target.value)}/>
               </label>
             </div>
             <div className="arc-risk-presets"><button onClick={()=>{setStopPct("3");setTakePct("6");}}>{t("3% stop / 6% target")}</button><button onClick={()=>{setStopPct("5");setTakePct("10");}}>{t("5% / 10%")}</button><button onClick={()=>{setStopPct("0");setTakePct("0");}}>{t("Off")}</button></div>
             <button className="arc-risk-save" disabled={busy||playing||viewingPast} onClick={()=> {
               const stop=Number(stopPct),take=Number(takePct);
               if (!Number.isFinite(stop)||!Number.isFinite(take)||stop<0||stop>75||take<0||take>75) {setError("Risk percentages must be between 0 and 75.");return;}
               void action(()=>gameSetRisk(game.id,stop,take),"Protective exits updated.");
             }}><ShieldCheck size={15}/> {t("Apply protection")}</button>
             <small>{t("Active: stop")} {game.risk.stop_loss_pct||t("off")}% · {t("target")} {game.risk.take_profit_pct||t("off")}%. If both levels are touched in one candle, the stop wins.</small>
           </div>
         </section>

         <section className="arc-pending-card">
           <div className="arc-box-head"><div><Target size={16}/><strong>{t("Pending orders")}</strong></div><span className="arc-tag">{game.orders.length}</span></div>
           {game.orders.length?game.orders.map(order=><div className="arc-pending" key={order.id}>
             <div><strong className={order.side==="buy"?"positive":"negative"}>{t(order.side.toUpperCase())} {order.size}{order.size_type==="percent"?"%":" units"}</strong><span>{t(order.kind.toUpperCase())}{order.price?" @ "+order.price:""} · {t(order.source)}</span></div>
             <button title={t("Cancel pending order")} disabled={busy||playing} onClick={()=>void action(()=>gameCancel(game.id,order.id))}><Trash2 size={15}/></button>
           </div>):<div className="arc-empty">{t("No pending orders.")}</div>}
         </section>

         <section className="arc-events">
           <div className="arc-box-head"><div><Sparkles size={17}/><strong>{t("Activity feed")}</strong></div></div>
           {game.events.slice(0,6).map((event,i)=><p key={i}><span className="arc-feed-dot"/>{t(event)}</p>)}
         </section>
         {error&&<div role="alert" className="arc-error arc-floating-error">{t(error)}<button onClick={()=>setError("")} aria-label={t("Dismiss error")}>{t("Dismiss")}</button></div>}
         {note&&!error&&<div role="status" className="arc-note"><Check size={15}/>{t(note)}<button onClick={()=>setNote("")} aria-label={t("Dismiss note")}>×</button></div>}
       </aside>
     </main>}
     <footer className="arc-footer"><span>{t("Historical trading research · Local simulation")}</span><span>{t("Bar-level approximations, not live exchange executions")}</span></footer>
  </div>;
}
