import "./marketDesk.css";
import { useI18n } from "./i18n";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowDownLeft, ArrowRight, ArrowUpRight, CandlestickChart,
  Check, ChevronDown, ChevronLeft, Clock3, Database, FastForward, LineChart, PauseCircle,
  Play, RefreshCw, RotateCcw, Search, ShieldCheck, Wallet, X,
} from "lucide-react";
import { PriceChart } from "./components/PriceChart";
import { ASSET_CLASSES, ASSETS as FALLBACK_ASSETS, formatMoney, formatPrice } from "./data/demoMarket";
import { gameCatalog, gameDiscover, gameImportTicker } from "./arcadeApi";
import type { DiscoveredInstrument } from "./arcadeApi";
import { getAccount, getBacktest, getHistory, getQuote, resetAccount, sendOrder, supportsCashTrading,
  getMarketCoverage,getMarketSubscriptions,subscribeMarket,unsubscribeMarket,getArchivedMarketHistory } from "./api";
import type { AccountResponse, BacktestResponse, HistoryResponse, QuoteResponse, MarketCoverage, MarketSubscription } from "./api";
import { advanceReplay, NEW_REPLAY, replayFillPrice, replayStartIndex } from "./replay";
import type { ReplayAccount } from "./replay";
import type { Asset, AssetClass, ChartStyle, TradeSide } from "./types";
import { REPLAY_WINDOWS, RESOLUTIONS } from "./replayIntervals";
import type { ReplayResolution, ReplayWindow } from "./replayIntervals";

const formatQuantity = (n: number) => n.toLocaleString("en-US", {maximumFractionDigits: 8});
const dt = (timestamp: number | string) =>
  new Date(typeof timestamp === "number" ? timestamp * 1000 : timestamp).toLocaleString(typeof document!=="undefined"&&document.documentElement.lang==="zh-CN"?"zh-CN":"en-CA");
const errorMessage = (err: unknown) => err instanceof Error ? err.message : "Unexpected error.";

type ReplayCheckpoint = {index:number;account:ReplayAccount};
const copyReplay = (account:ReplayAccount):ReplayAccount => JSON.parse(JSON.stringify(account)) as ReplayAccount;

export default function MarketDesk() {
  const {t} = useI18n();
  const [catalog, setCatalog] = useState<Asset[]>(FALLBACK_ASSETS);
  const [remoteMatches,setRemoteMatches] = useState<DiscoveredInstrument[]>([]);
  const [catalogBusy,setCatalogBusy] = useState(false);
  const [catalogError,setCatalogError] = useState("");
  const [terminalTab,setTerminalTab] = useState<"market"|"portfolio"|"research">("market");
  const [assetClass, setAssetClass] = useState<AssetClass>("Stocks");
  const [selectedId, setSelectedId] = useState("aapl");
  const [search, setSearch] = useState("");
  const [resolution, setResolution] = useState<ReplayResolution>("1d");
  const [range, setRange] = useState<ReplayWindow>("MAX");
  const [chartStyle, setChartStyle] = useState<ChartStyle>("candles");
  const [mode, setMode] = useState<"market" | "replay">("market");
  const [side, setSide] = useState<TradeSide>("buy");
  const [quantity, setQuantity] = useState("1");
  const [history, setHistory] = useState<HistoryResponse | null>(null);
  const [coverage,setCoverage]=useState<MarketCoverage|null>(null);
  const [subscriptions,setSubscriptions]=useState<MarketSubscription[]>([]);
  const [marketOpsBusy,setMarketOpsBusy]=useState(false);
  const [marketOpsError,setMarketOpsError]=useState("");
  const tracking=subscriptions.find(x=>x.asset_id===selectedId&&x.resolution===resolution&&x.active);
  const [quote, setQuote] = useState<QuoteResponse | null>(null);
  const [lastQuotes, setLastQuotes] = useState<Record<string, QuoteResponse>>({});
  const [account, setAccount] = useState<AccountResponse | null>(null);
  const [backendOnline, setBackendOnline] = useState(false);
  const [loadingMarket, setLoadingMarket] = useState(false);
  const [marketError, setMarketError] = useState("");
  const [tradeError, setTradeError] = useState("");
  const [notice, setNotice] = useState("");
  const [placing, setPlacing] = useState(false);
  const [activePanel, setActivePanel] = useState<"positions" | "history">("positions");
  const [replayIndex, setReplayIndex] = useState(0);
  const [replayAccount, setReplayAccount] = useState<ReplayAccount>({...NEW_REPLAY});
  const [replayCheckpoints,setReplayCheckpoints] = useState<ReplayCheckpoint[]>([]);
  const [inspectState,setInspectState] = useState<ReplayCheckpoint|null>(null);
  const [showBacktest, setShowBacktest] = useState(false);
  const [fast, setFast] = useState("10");
  const [slow, setSlow] = useState("30");
  const [backtest, setBacktest] = useState<BacktestResponse | null>(null);
  const [backtestError, setBacktestError] = useState("");
  const [runningBacktest, setRunningBacktest] = useState(false);
  const selectedAsset = catalog.find(asset => asset.id === selectedId) ?? catalog[0] ?? FALLBACK_ASSETS[0];
  useEffect(()=>{
    let active=true;
    void gameCatalog().then(items=>{
      if(!active)return;
      setCatalog(items.map(item=>{
        const existing=FALLBACK_ASSETS.find(asset=>asset.id===item.id);
        return {
          id:item.id,symbol:item.symbol,name:item.name,
          exchange:existing?.exchange??item.currency,
          assetClass:item.asset_class as AssetClass,decimals:item.decimals,
          spreadBps:existing?.spreadBps??5,accent:existing?.accent??"#78b6cb",
        };
      }));
    }).catch(()=>{if(active)setCatalogError("Instrument catalog is unavailable. Showing fallback instruments.");});
    return ()=>{active=false;};
  },[]);
  async function findRemote(){
    if(search.trim().length<2)return;
    setCatalogBusy(true);setCatalogError("");
    try{setRemoteMatches(await gameDiscover(search.trim()));}
    catch(e){setCatalogError(errorMessage(e));}
    finally{setCatalogBusy(false);}
  }
  async function importRemote(symbol:string){
    setCatalogBusy(true);setCatalogError("");
    try {
      const item=await gameImportTicker(symbol);
      setCatalog(previous=>previous.some(a=>a.id===item.id)?previous:[...previous,{
        id:item.id,symbol:item.symbol,name:item.name,exchange:item.currency,
        assetClass:item.asset_class as AssetClass,decimals:item.decimals,
        spreadBps:5,accent:"#78b6cb",
      }]);
      setSelectedId(item.id);setRemoteMatches([]);setSearch("");
    }catch(e){setCatalogError(errorMessage(e));}
    finally{setCatalogBusy(false);}
  }
  const supported = supportsCashTrading(selectedAsset.id, selectedAsset.assetClass);
  const allBars = history?.asset_id === selectedId ? history.bars : [];
  const visibleBars = useMemo(() => mode === "replay" ? allBars.slice(0, replayIndex + 1) : allBars, [mode, allBars, replayIndex]);
  const latestCandle = visibleBars.at(-1);
  const previousCandle = visibleBars.length > 1 ? visibleBars[visibleBars.length - 2] : undefined;
  const currency = history?.currency ?? (selectedId === "vfv" ? "CAD" : "USD");
  const snapshot = mode === "replay" ? latestCandle?.close : quote?.asset_id === selectedId ? quote.price : latestCandle?.close;
  const change = latestCandle && previousCandle ? latestCandle.close - previousCandle.close : null;
  const changePct = change !== null && previousCandle ? (change / previousCandle.close) * 100 : null;
  const high = visibleBars.length ? Math.max(...visibleBars.map(bar => bar.high)) : null;
  const low = visibleBars.length ? Math.min(...visibleBars.map(bar => bar.low)) : null;
  const quoteReady = quote?.asset_id === selectedId && quote.tradable;
  const parsedQuantity = Number(quantity);
  const wholeUnits = selectedAsset.assetClass === "Stocks" || selectedAsset.assetClass === "ETFs" || selectedAsset.assetClass === "Options" || selectedAsset.assetClass === "Futures";
  const validQuantity = Number.isFinite(parsedQuantity) && parsedQuantity > 0 && parsedQuantity <= 100_000_000 &&
    (!wholeUnits || Number.isInteger(parsedQuantity)) && (!quantity.includes(".") || quantity.split(".")[1].length <= 8);
  const indicativeFill = mode === "replay"
    ? (latestCandle && replayFillPrice(selectedAsset, side, latestCandle.close))
    : quote && (quote.bid !== null && quote.ask !== null
      ? (side === "buy" ? quote.ask : quote.bid) * (side === "buy" ? 1.0002 : 0.9998)
      : quote.price * (side === "buy" ? 1 + quote.spread_bps / 20000 + 0.0002 : 1 - quote.spread_bps / 20000 - 0.0002));
  const estimate = validQuantity && indicativeFill ? parsedQuantity * indicativeFill : 0;

  useEffect(()=>{
    let active=true;
    const load=()=>{
      void getMarketSubscriptions().then(items=>{if(active)setSubscriptions(items);}).catch(()=>{});
    };
    load();const timer=setInterval(load,30000);
    return()=>{active=false;clearInterval(timer);};
  },[]);
  useEffect(()=>{
    let active=true;
    // Data quality is measured from recorded bars, without another Yahoo
    // request. It cannot invent missing candles or claim exchange accuracy.
    setCoverage(null);
    void getMarketCoverage(selectedId,range,resolution).then(value=>{
      if(active)setCoverage(value);
    }).catch(()=>{});
    return()=>{active=false;};
  },[selectedId,range,resolution,history?.as_of]);
  async function setTracking(){
    setMarketOpsBusy(true);setMarketOpsError("");
    try {
      if(tracking)await unsubscribeMarket(selectedId,resolution);
      else await subscribeMarket(selectedId,resolution);
      setSubscriptions(await getMarketSubscriptions());
    }catch(e){setMarketOpsError(errorMessage(e));}
    finally{setMarketOpsBusy(false);}
  }

  const loadAccount = useCallback(async () => {
    try { setAccount(await getAccount()); setBackendOnline(true); }
    catch (error) { setBackendOnline(false); setTradeError(errorMessage(error)); }
  }, []);

  useEffect(() => { void loadAccount(); }, [loadAccount]);

  // Ingestion-enabled charts read the already-recorded local archive.
  // Do not refetch the entire Yahoo/Coinbase history every two minutes.
  // Replay remains immutable while the user is backtesting history.
  useEffect(() => {
    if (mode !== "market") return;
    let cancelled = false;
    const timer = setInterval(() => {
      const load=tracking
        ? getArchivedMarketHistory(selectedId,range,resolution)
        : getHistory(selectedId,range,resolution);
      void load.then(next => { if (!cancelled) setHistory(next); })
        .catch(() => {});
    }, 120_000);
    return () => { cancelled = true; clearInterval(timer); };
  }, [mode, selectedId, range, resolution, !!tracking]);

  useEffect(() => {
    let cancelled = false;
    setLoadingMarket(true);
    setMarketError("");
    setHistory(null);
    setQuote(null);
    setBacktest(null);
    setReplayAccount({...NEW_REPLAY});
    setReplayCheckpoints([]);
    setInspectState(null);
    const load = async () => {
      const [h, q] = await Promise.allSettled([getHistory(selectedId, range, resolution), getQuote(selectedId)]);
      if (cancelled) return;
      if (h.status === "fulfilled") {
        setHistory(h.value);
        const start=replayStartIndex(h.value.bars.length);
        setReplayIndex(start);
        setReplayCheckpoints([{index:start,account:copyReplay(NEW_REPLAY)}]);
        setInspectState(null);
        setBackendOnline(true);
      } else setMarketError(errorMessage(h.reason));
      if (q.status === "fulfilled") {
        setQuote(q.value);
        setLastQuotes(prev => ({...prev, [selectedId]: q.value}));
        setBackendOnline(true);
      } else if (h.status !== "fulfilled") setMarketError(errorMessage(q.reason));
      setLoadingMarket(false);
    };
    void load();
    const poll = setInterval(async () => {
      try {
        const next = await getQuote(selectedId);
        if (!cancelled) {
          setQuote(next);
          setLastQuotes(prev => ({...prev, [selectedId]: next}));
        }
      } catch {
        if (!cancelled) setQuote(null);
      }
    }, 45_000);
    return () => { cancelled = true; clearInterval(poll); };
  }, [selectedId, range, resolution]);

  function selectAsset(asset: Asset) {
    setSelectedId(asset.id);
    setQuantity("1");
    setTradeError("");
    setNotice("");
  }
  function changeClass(next: AssetClass) {
    setAssetClass(next);
    setSearch("");
    selectAsset(catalog.find(asset => asset.assetClass === next) ?? catalog[0]);
  }
  function changeMode(next: "market" | "replay") {
    setMode(next);
    setTradeError("");
    setNotice("");
    if (next === "replay") {
      const start=replayStartIndex(allBars.length);
      setReplayIndex(start);
      setReplayAccount({...NEW_REPLAY});
      setReplayCheckpoints([{index:start,account:copyReplay(NEW_REPLAY)}]);
      setInspectState(null);
    }
  }
  function resetReplay() {
    const start=replayStartIndex(allBars.length);
    setReplayIndex(start);
    setReplayAccount({...NEW_REPLAY});
    setReplayCheckpoints([{index:start,account:copyReplay(NEW_REPLAY)}]);
    setInspectState(null);
    setNotice("Replay reset. Previous replay orders were cleared.");
    setTradeError("");
  }
  function stepReplay(count = 1) {
    if (inspectState || !allBars.length || replayIndex >= allBars.length - 1) return;
    let next = replayAccount;
    let message: string | undefined;
    const additions:ReplayCheckpoint[]=[];
    const end = Math.min(replayIndex + count, allBars.length - 1);
    for (let i = replayIndex + 1; i <= end; i++) {
      const result = advanceReplay(next, allBars[i], selectedAsset);
      next = result.account;
      additions.push({index:i,account:copyReplay(next)});
      if (result.message) message = result.message;
    }
    setReplayIndex(end);
    setReplayAccount(next);
    setReplayCheckpoints(prev=>[...prev,...additions].slice(-1500));
    if (message) setNotice(message);
    setTradeError("");
  }
  function inspectReplayAt(index:number) {
    const old=replayCheckpoints.find(entry=>entry.index===index);
    if(!old)return;
    if(!inspectState)setInspectState({index:replayIndex,account:copyReplay(replayAccount)});
    setReplayIndex(index);setReplayAccount(copyReplay(old.account));
    setTradeError("");
  }
  function returnToLatestReplay() {
    if(!inspectState)return;
    setReplayIndex(inspectState.index);
    setReplayAccount(copyReplay(inspectState.account));
    setInspectState(null);
    setTradeError("");
  }
  async function placeOrder(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTradeError("");
    if (mode==="replay" && inspectState) {setTradeError("Historical inspection is read-only. Return to latest to trade.");return;}
    if (!validQuantity) { setTradeError(wholeUnits ? "Enter a positive whole-unit quantity." : "Enter a positive quantity with at most 8 decimals."); return; }
    if (!supported) { setTradeError("This asset is chart-only until its contract and currency rules are implemented."); return; }
    if (mode === "replay") {
      if (!allBars.length || replayIndex >= allBars.length - 1) {setTradeError("Replay is at the final candle."); return;}
      if (replayAccount.pending) {setTradeError("Step forward to fill the existing pending order first."); return;}
      if (side === "sell" && parsedQuantity > replayAccount.quantity + 1e-9) {setTradeError("Not enough replay holdings."); return;}
      // Do not inspect the next bar to fill this order. It fills only when the user advances.
      const queued={...replayAccount,pending:{side,quantity:parsedQuantity}};
      setReplayAccount(queued);
      setReplayCheckpoints(prev=>prev.map(entry=>entry.index===replayIndex
        ? {index:replayIndex,account:copyReplay(queued)}:entry));
      setNotice(`Replay ${side} queued. Advance one candle to simulate execution at the next open.`);
      return;
    }
    if (!quoteReady) {setTradeError(quote?.block_reason ?? "No fresh tradable quote available."); return;}
    setPlacing(true);
    try {
      const response = await sendOrder(selectedId, side, quantity);
      setAccount(response.account);
      setNotice(`Paper ${side} filled: ${formatQuantity(parsedQuantity)} ${selectedAsset.symbol} at ${formatPrice(response.fill.price, selectedAsset.decimals)}. Fee: ${formatMoney(response.fill.fee)}.`);
      setActivePanel("history");
      setTerminalTab("portfolio");
      setQuantity("1");
    } catch (error) {setTradeError(errorMessage(error));}
    finally {setPlacing(false);}
  }
  async function resetPortfolio() {
    if (mode === "replay") {resetReplay(); return;}
    if (!window.confirm("Delete all local paper orders and reset to $100,000?")) return;
    try {
      setAccount(await resetAccount());
      setNotice("Local paper account reset.");
      setTradeError("");
    } catch (error) {setTradeError(errorMessage(error));}
  }
  async function runBacktest() {
    const f = Number(fast), s = Number(slow);
    if (!Number.isInteger(f) || !Number.isInteger(s) || f < 2 || f >= s || s > 100) {
      setBacktestError("Use whole numbers where 2 <= fast < slow <= 100.");
      return;
    }
    setRunningBacktest(true);
    setBacktestError("");
    setBacktest(null);
    try {setBacktest(await getBacktest(selectedId, f, s));}
    catch (error) {setBacktestError(errorMessage(error));}
    finally {setRunningBacktest(false);}
  }

  const held = mode === "replay" ? replayAccount.quantity : (account?.positions.find(position => position.asset_id === selectedId)?.quantity ?? 0);
  const replayExposure = replayAccount.quantity * (latestCandle?.close ?? 0);
  const totalCash = mode === "replay" ? replayAccount.cash : account?.cash;
  const equity = mode === "replay" ? replayAccount.cash + replayExposure : account?.equity;
  const exposure = mode === "replay" ? replayExposure : account?.positions.reduce((sum, position) => sum + (position.market_value ?? 0), 0);
  const unrealized = mode === "replay" ? replayAccount.quantity * ((latestCandle?.close ?? 0) - replayAccount.averageCost) : account?.unrealized_pnl;
  const openCount = mode === "replay" ? (replayAccount.quantity > 1e-9 ? 1 : 0) : (account?.positions.length ?? 0);
  const tradeCount = mode === "replay" ? replayAccount.fills.length : (account?.fills.length ?? 0);
  const canTrade = supported && validQuantity && (mode === "replay" ? allBars.length > 2 && replayIndex < allBars.length - 1 && !replayAccount.pending : !!quoteReady);

  const watchlist = catalog.filter(asset => asset.assetClass === assetClass &&
    `${asset.symbol} ${asset.name}`.toLowerCase().includes(search.trim().toLowerCase()));

  return (
    <div className="market-desk">
      <header className="market-desk-head">
        <div><span className="market-desk-kicker">{t("LIVE MARKET RESEARCH")}</span>
          <h2>{t("Market Data & Paper Trading")}</h2>
          <p>{t("Watchlists, historical charts, quote snapshots, portfolio ledger and SMA backtests, integrated into the Trading Simulator.")}</p></div>
        <div className="market-desk-actions">
          <span className={backendOnline?"market-desk-online":"market-desk-offline"}>{t(backendOnline?"LOCAL API ONLINE":"API OFFLINE")}</span>
          <strong>{equity==null?t("Unavailable"):formatMoney(equity)}</strong>
          <button type="button" onClick={()=>void resetPortfolio()}><RotateCcw size={15}/>{t("Reset paper account")}</button>
        </div>
      </header>
      <div className="market-desk-notice"><Database size={14}/>{t("Public quotes may be delayed. Orders are simulated. Historical replay remains isolated from the paper account.")}</div>

      <div className="workspace" data-terminal-tab={terminalTab}>
        <nav className="terminal-workspace-tabs" aria-label={t("Workspace sections")}>
          {(["market","portfolio","research"] as const).map(tab=><button type="button" key={tab}
            className={terminalTab===tab?"selected":""} aria-current={terminalTab===tab?"page":undefined}
            onClick={()=>setTerminalTab(tab)}>{t(tab==="market"?"Market & Charts":tab==="portfolio"?"Account & Orders":"Backtest Research")}</button>)}
        </nav>
        <aside className="watchlist-panel">
          <div className="watchlist-heading"><div><span className="eyebrow">{t("MARKET EXPLORER")}</span><h2>{t("Watchlist")}</h2></div><span className="subtle-counter">{catalog.length} {t("assets")}</span></div>
          <label className="search-field"><Search size={16}/>
            <input type="search" value={search} onChange={e => setSearch(e.target.value)} placeholder={t("Search symbols...")} aria-label={t("Search symbols")}/>
          </label>
          <div className="category-tabs" role="tablist" aria-label={t("Asset classes")}>
            {ASSET_CLASSES.map(group =>
              <button key={group} type="button" role="tab" aria-selected={assetClass===group} className={assetClass===group?"category-active":""} onClick={() => changeClass(group)}>{t(group)}</button>)}
          </div>
          <div className="market-catalog-actions">
            <button type="button" disabled={catalogBusy||search.trim().length<2} onClick={()=>void findRemote()}>
              {t("Search provider")}
            </button>
            {catalogError&&<small role="alert">{catalogError}</small>}
            {remoteMatches.length>0&&<div className="market-catalog-matches">
              {remoteMatches.slice(0,6).map(item=><button key={item.symbol} type="button"
                disabled={catalogBusy} onClick={()=>void importRemote(item.symbol)}>
                {item.symbol} · {item.name} <span>{t("Import")}</span>
              </button>)}
            </div>}
          </div>
          <div className="watchlist-table-label"><span>{t("SYMBOL / NAME")}</span><span>{t("LAST KNOWN / STATUS")}</span></div>
          <div className="watchlist-items">
            {watchlist.length === 0 ? <div className="watch-empty">{t("No symbols match your search.")}</div> : watchlist.map(asset => {
              const q = lastQuotes[asset.id];
              return <button type="button" key={asset.id} className={`asset-item ${selectedId === asset.id ? "asset-selected" : ""}`} onClick={() => selectAsset(asset)}>
                <span className="asset-icon" style={{"--asset-accent":asset.accent} as React.CSSProperties}>{asset.symbol.slice(0,1)}</span>
                <span className="asset-details"><strong>{asset.symbol}</strong><small>{asset.name}</small></span>
                <span className="asset-quote"><strong>{q ? formatPrice(q.price, asset.decimals) : "—"}</strong><small className={q?.tradable ? "positive" : ""}>{t(q ? (q.tradable ? "Quote ready" : q.block_reason ?? "Indicative") : "Not loaded")}</small></span>
              </button>;
            })}
          </div>
          <div className="sidebar-bottom"><div className="sidebar-info-icon"><ShieldCheck size={18}/></div><div><strong>{t("Local paper account")}</strong><span>{t("No broker connection or real orders.")}</span></div></div>
        </aside>

        <section className="center-column">
          <div className="instrument-header">
            <div className="instrument-title"><div className="symbol-logo" style={{"--asset-accent": selectedAsset.accent} as React.CSSProperties}>{selectedAsset.symbol[0]}</div>
              <div><div className="instrument-name"><h1>{selectedAsset.symbol}</h1><span className="market-badge">{t(selectedAsset.assetClass)}</span></div><p>{selectedAsset.name} <span>·</span> {selectedAsset.exchange}</p></div>
            </div>
            <div className="instrument-price"><strong>{snapshot == null ? "—" : formatPrice(snapshot, selectedAsset.decimals)} <small>{currency}</small></strong>
              <span className={change === null ? "" : change >= 0 ? "positive" : "negative"}>
                {change !== null && (change >= 0 ? <ArrowUpRight size={14}/> : <ArrowDownLeft size={14}/>)}
                {change === null ? t("No market data") : `${change >= 0 ? "+" : ""}${formatPrice(change, selectedAsset.decimals)} (${changePct! >= 0 ? "+" : ""}${changePct!.toFixed(2)}%)`}
                <small> {t("/ LAST TWO BARS")}</small>
              </span>
            </div>
          </div>

          <div className="market-stats">
            <div><span>{t(quote?.bid == null ? "BID / MODEL" : "EXCHANGE BID")}</span><strong>{mode==="replay" ? "—" : quote?.bid != null ? formatPrice(quote.bid, selectedAsset.decimals) : "Unavailable"}</strong></div>
            <div><span>{t(quote?.ask == null ? "ASK / MODEL" : "EXCHANGE ASK")}</span><strong>{mode==="replay" ? "—" : quote?.ask != null ? formatPrice(quote.ask, selectedAsset.decimals) : "Unavailable"}</strong></div>
            <div><span>{t("VISIBLE HIGH")}</span><strong>{high == null ? "—" : formatPrice(high, selectedAsset.decimals)}</strong></div>
            <div><span>{t("VISIBLE LOW")}</span><strong>{low == null ? "—" : formatPrice(low, selectedAsset.decimals)}</strong></div>
            <div className="market-stats-source"><span className="muted-dot"/>{t(loadingMarket ? "LOADING" : quote?.source?.includes("Coinbase") ? "COINBASE" : "INDICATIVE")}</div>
          </div>

          <section className="chart-card">
            <div className="chart-toolbar">
              <div className="chart-toolbar-label"><CandlestickChart size={17}/><strong>{t("Price chart")}</strong><span className="demo-pill">{t(history ? "HISTORICAL OHLCV" : "NO DATA")}</span></div>
              <div className="chart-actions">
                <label className="terminal-interval-picker">{t("Candle interval")}
                  <select value={resolution} onChange={e=>{
                    const next=e.target.value as ReplayResolution;
                    setResolution(next);setRange(next==="1d"?"MAX":REPLAY_WINDOWS[next][0]);
                  }}>{RESOLUTIONS.map(i=><option key={i} value={i}>{i}</option>)}</select>
                </label>
                <div className="timeframe-control" aria-label={t("Timeframe")}>{REPLAY_WINDOWS[resolution].map(period =>
                  <button type="button" key={period} className={range===period ? "control-active" : ""} aria-pressed={range===period} onClick={() => setRange(period)}>{period}</button>)}
                </div><div className="toolbar-separator"/>
                <div className="style-control"><button type="button" className={chartStyle==="candles"?"control-active":""} title={t("Candlesticks")} aria-label={t("Candlestick view")} onClick={()=>setChartStyle("candles")}><CandlestickChart size={17}/></button>
                  <button type="button" className={chartStyle==="line"?"control-active":""} title={t("Line")} aria-label={t("Line view")} onClick={()=>setChartStyle("line")}><LineChart size={17}/></button></div>
              </div>
            </div>
            <div className="chart-mode-bar">
              <div className="mode-tabs">
                <button type="button" className={mode==="market"?"mode-selected":""} onClick={()=>changeMode("market")}><Activity size={14}/> {t("Market")}</button>
                <button type="button" className={mode==="replay"?"mode-selected":""} onClick={()=>changeMode("replay")}><Clock3 size={14}/> {t("Replay")}</button>
              </div>
              <div className="market-data-health">
                <div className="market-data-health-line">
                  <strong>{t("Latest provider quote")}</strong>
                  <span>{quote?.source??t("Not available")}</span>
                  <span>{quote?.timestamp?dt(quote.timestamp):t("No quote timestamp")}</span>
                  <span>{quote?.as_of_age_seconds!=null?`${Math.round(quote.as_of_age_seconds)}s ${t("source age")}`:t("Unknown source age")}</span>
                  <span>{quote?.fresh?t("Within freshness threshold"):t("Stale or unavailable quote")}</span>
                </div>
                <div className="market-data-health-line">
                  <strong>{t("Local data coverage")}</strong>
                  <span>{coverage?.bars??0} {t("recorded bars")}</span>
                  <span>{coverage?.coverage_pct==null?t("Coverage varies by session"):`${coverage.coverage_pct}% ${t("weekday coverage estimate")}`}</span>
                  <span>{coverage?.gaps?.length??0} {t("possible observed gaps")}</span>
                  <span>{coverage?.last_bar?t("Latest archived")+" "+dt(coverage.last_bar):t("No archived candles")}</span>
                </div>
                <div className="market-data-health-line">
                  <strong>{t("Incremental ingestion")}</strong>
                  <span>{tracking?t("Tracking active"):t("Not tracking")}</span>
                  {tracking?.last_success&&<span>{t("Last successful sync")} {dt(tracking.last_success)}</span>}
                  {tracking?.failure_code&&<span role="alert">{t("Provider status")} {tracking.failure_code}</span>}
                  <button type="button" disabled={marketOpsBusy}
                    onClick={()=>void setTracking()}>{t(tracking?"Stop collecting":"Collect new bars locally")}</button>
                </div>
                {marketOpsError&&<small role="alert">{marketOpsError}</small>}
              </div>
              <span>{history ? `${history.source} · ${t("latest bar")} ${dt(history.bars.at(-1)!.time)}` : t("Connect local API for market history")}</span>
            </div>
            <div className="chart-body">
              {visibleBars.length ? <PriceChart asset={selectedAsset} range="1Y" style={chartStyle} bars={visibleBars}/> :
                <div className="chart-placeholder">{loadingMarket ? <RefreshCw size={26} className="spin"/> : <Database size={26}/>}
                  <strong>{t(loadingMarket ? "Fetching market history" : "Chart not available")}</strong>
                  <span>{t(marketError || "Start the Python API and select an available instrument.")}</span>
                </div>}
            </div>
            {mode==="replay" && <div className="replay-controls">
              <button type="button" onClick={resetReplay} title={t("Restart replay")}><RotateCcw size={15}/> {t("Restart")}</button>
              <div className="replay-progress"><span>{t("BAR")} {visibleBars.length} / {allBars.length}</span><span>{latestCandle ? dt(latestCandle.time) : "—"}</span></div>
              <button type="button" disabled={replayCheckpoints.length<2||replayIndex<=replayCheckpoints[0].index}
                onClick={()=>inspectReplayAt(replayIndex-1)}><ChevronLeft size={15}/>{t("Previous step")}</button>
              {inspectState&&<><button type="button" disabled={replayIndex>=inspectState.index}
                onClick={()=>inspectReplayAt(replayIndex+1)}>{t("Next recorded step")}</button>
                <button type="button" onClick={returnToLatestReplay}>{t("Return to latest")}</button></>}
              <button type="button" onClick={()=>stepReplay(1)} disabled={!!inspectState||!allBars.length || replayIndex >= allBars.length-1}><Play size={16}/> {t("Next")}</button>
              <button type="button" onClick={()=>stepReplay(5)} disabled={!!inspectState||!allBars.length || replayIndex >= allBars.length-1}><FastForward size={17}/> +5</button>
            </div>}
            <div className="chart-footer"><span><span className="legend-dot up-dot"/> {t("Up")} <span className="legend-dot down-dot"/> {t("Down")} <span className="legend-volume"/> {t("Volume")}</span>
              <span>{t(mode==="replay" ? "No future bars displayed" : "Historical data, not tick-by-tick")} · <a href="https://www.tradingview.com/" target="_blank" rel="noreferrer">{t("Charts by TradingView")}</a></span>
            </div>
          </section>

          <section className="portfolio-card" id="portfolio-panel">
            <div className="section-heading"><div><span className="eyebrow">{t(mode==="replay"?"ISOLATED REPLAY ACCOUNT":"SQLITE PAPER ACCOUNT")}</span><h2>{t("Portfolio overview")}</h2></div><span className="sim-account"><span className="local-dot"/> {t("PAPER ACCOUNT")}</span></div>
            <div className="portfolio-metrics">
              <div><span>{t("NET LIQUIDATION")}</span><strong>{equity == null ? "—" : formatMoney(equity)}</strong><small>{t(mode==="replay"?"At current replay close":"Unavailable if any mark missing")}</small></div>
              <div><span>{t("AVAILABLE CASH")}</span><strong>{totalCash == null ? "—" : formatMoney(totalCash)}</strong><small>{t("USD cash-only")}</small></div>
              <div><span>{t("MARKET EXPOSURE")}</span><strong>{exposure == null ? "—" : formatMoney(exposure)}</strong><small>{openCount} {t("open instruments")}</small></div>
              <div><span>{t("UNREALIZED P&L")}</span><strong className={unrealized == null ? "" : unrealized >= 0 ? "positive" : "negative"}>{unrealized == null ? "—" : formatMoney(unrealized)}</strong><small>{t("Without simulated exit costs")}</small></div>
            </div>
            <div className="portfolio-tab-row"><div className="portfolio-tabs" role="tablist" aria-label={t("Portfolio view")}>
              <button role="tab" aria-selected={activePanel==="positions"} className={activePanel==="positions"?"portfolio-tab-active":""} onClick={()=>setActivePanel("positions")}>{t("Positions")} <span>{openCount}</span></button>
              <button role="tab" aria-selected={activePanel==="history"} className={activePanel==="history"?"portfolio-tab-active":""} onClick={()=>setActivePanel("history")}>{t("Fills")} <span>{tradeCount}</span></button>
            </div></div>
            <div className="table-scroll">
              {activePanel==="positions" ? (
                mode==="replay" ? replayAccount.quantity > 0 ? <table className="data-table"><thead><tr><th>{t("ASSET")}</th><th>{t("QUANTITY")}</th><th>{t("AVERAGE COST")}</th><th>{t("MARKET VALUE")}</th><th>{t("UNREALIZED P&L")}</th></tr></thead><tbody><tr>
                  <td><strong>{selectedAsset.symbol}</strong></td><td>{formatQuantity(replayAccount.quantity)}</td>
                  <td>{formatPrice(replayAccount.averageCost, selectedAsset.decimals)}</td><td>{formatMoney(replayExposure)}</td><td className={unrealized! >= 0?"positive":"negative"}>{formatMoney(unrealized!)}</td>
                </tr></tbody></table> : <div className="empty-state"><Wallet size={25}/><strong>{t("No replay positions")}</strong><span>{t("Queue a buy and advance to the next candle.")}</span></div>
                  : account?.positions.length ? <table className="data-table"><thead><tr><th>{t("ASSET")}</th><th>{t("QUANTITY")}</th><th>{t("AVERAGE COST")}</th><th>{t("MARKET VALUE")}</th><th>{t("UNREALIZED P&L")}</th></tr></thead>
                    <tbody>{account.positions.map(position => {
                      const asset = catalog.find(item => item.id === position.asset_id);
                      return <tr key={position.asset_id}><td><strong>{asset?.symbol ?? position.asset_id}</strong><small>{asset?.assetClass?t(asset.assetClass):""}</small></td><td>{formatQuantity(position.quantity)}</td>
                        <td>{formatPrice(position.average_cost, asset?.decimals ?? 2)}</td><td>{position.market_value === null ? t("Unpriced") : formatMoney(position.market_value)}</td>
                        <td className={position.unrealized_pnl == null ? "" : position.unrealized_pnl >= 0?"positive":"negative"}>{position.unrealized_pnl === null ? "—" : formatMoney(position.unrealized_pnl)}</td>
                      </tr>;
                    })}</tbody></table>
                  : <div className="empty-state"><Wallet size={25}/><strong>{t("No open positions")}</strong><span>{t("Buy a supported instrument when its market is open.")}</span></div>
              ) : (
                (mode==="replay" ? replayAccount.fills.length>0 : !!account?.fills.length) ?
                  <table className="data-table"><thead><tr><th>{t("TIME")}</th><th>{t("SYMBOL")}</th><th>{t("SIDE")}</th><th>{t("QTY")}</th><th>{t("FILL PRICE")}</th><th>{t("FEE")}</th></tr></thead>
                    <tbody>{mode==="replay" ? replayAccount.fills.map((fill, index) => <tr key={index}>
                      <td>{dt(fill.time)}</td><td><strong>{selectedAsset.symbol}</strong></td>
                      <td className={fill.side==="buy"?"positive":"negative"}>{t(fill.side.toUpperCase())}</td><td>{formatQuantity(fill.quantity)}</td><td>{formatPrice(fill.price, selectedAsset.decimals)}</td><td>{formatMoney(fill.fee)}</td>
                    </tr>) : account?.fills.map(fill => <tr key={fill.id}>
                      <td>{dt(fill.created_at)}</td><td><strong>{catalog.find(a=>a.id===fill.asset_id)?.symbol ?? fill.asset_id}</strong></td>
                      <td className={fill.side==="buy"?"positive":"negative"}>{t(fill.side.toUpperCase())}</td><td>{formatQuantity(fill.quantity)}</td>
                      <td>{formatPrice(fill.price, catalog.find(a=>a.id===fill.asset_id)?.decimals ?? 2)}</td><td>{formatMoney(fill.fee)}</td>
                    </tr>)}</tbody></table>
                  : <div className="empty-state"><Clock3 size={25}/><strong>{t("No executed orders")}</strong><span>{t("Paper fills will appear here.")}</span></div>
              )}
            </div>
          </section>

          <section className="portfolio-card strategy-card">
            <div className="section-heading">
              <div><span className="eyebrow">{t("HISTORICAL RESEARCH")}</span><h2>{t("Strategy backtester")}</h2></div>
              <button type="button" className="text-link" onClick={()=>setShowBacktest(v=>!v)}>{t(showBacktest ? "Collapse" : "Configure")} <ChevronDown size={15}/></button>
            </div>
            {showBacktest && <div className="strategy-body">
              <p>{t("Backtest an SMA crossover using one year of actual daily candles. Signal at bar close; modeled execution at the")} <strong>{t("next bar open")}</strong>.</p>
              <div className="strategy-settings"><label>{t("Fast MA (days)")}<input type="number" min="2" max="99" value={fast} onChange={e=>setFast(e.target.value)}/></label>
                <label>{t("Slow MA (days)")}<input type="number" min="3" max="100" value={slow} onChange={e=>setSlow(e.target.value)}/></label>
                <button type="button" disabled={runningBacktest || !supported} onClick={()=>void runBacktest()}><Play size={15}/>{t(runningBacktest ? "Running..." : "Run backtest")}</button>
              </div>
              {backtestError && <p className="form-error">{t(backtestError)}</p>}
              {!supported && <p className="support-text">{t("This instrument does not yet support the USD cash strategy engine.")}</p>}
              {backtest && <div className="backtest-results">
                <div><span>{t("STRATEGY RETURN")}</span><strong className={backtest.return_pct>=0?"positive":"negative"}>{backtest.return_pct.toFixed(2)}%</strong></div>
                <div><span>{t("BUY AND HOLD")}</span><strong>{backtest.buy_hold_pct.toFixed(2)}%</strong></div>
                <div><span>{t("MAX DRAWDOWN")}</span><strong className="negative">{backtest.max_drawdown_pct.toFixed(2)}%</strong></div>
                <div><span>{t("EXECUTED ORDERS")}</span><strong>{backtest.trades.length}</strong></div>
                <p>{backtest.execution}. This does not model intrabar fills or market impact.</p>
              </div>}
            </div>}
          </section>
        </section>

        <aside className="ticket-column">
          <section className="ticket-card">
            <div className="ticket-heading"><div><span className="eyebrow">{t(mode==="replay"?"NEXT-BAR EXECUTION":"PAPER EXECUTION")}</span><h2>{t("Order ticket")}</h2></div><span className="ticket-icon"><ArrowRight size={18}/></span></div>
            <div className="ticket-security"><span className="ticket-security-symbol">{selectedAsset.symbol}</span><span className="ticket-security-class">{t(selectedAsset.assetClass)}<ChevronDown size={12}/></span></div>
            <label className="terminal-order-asset-picker">{t("Instrument")}
              <select value={selectedId} onChange={event=>{
                const next=catalog.find(asset=>asset.id===event.target.value);
                if(next){setAssetClass(next.assetClass);setSearch("");selectAsset(next);}
              }}>
                {catalog.map(asset=><option key={asset.id} value={asset.id}>{asset.symbol} · {asset.name}</option>)}
              </select>
            </label>
            <div className="side-switch">
              <button type="button" className={side==="buy"?"buy-active":""} onClick={()=>{setSide("buy");setTradeError("");}}>{t("Buy / Long")}</button>
              <button type="button" className={side==="sell"?"sell-active":""} onClick={()=>{setSide("sell");setTradeError("");}}>{t("Sell / Close")}</button>
            </div>
            <form onSubmit={e=>void placeOrder(e)}>
              <div className="field-head"><label htmlFor="order-type">{t("Order type")}</label></div>
              <select id="order-type" value="market" onChange={()=>{}} aria-label={t("Order type")}><option value="market">{t(mode==="replay"?"Next-bar open (replay)":"Market (modeled)")}</option></select>
              <div className="field-head"><label htmlFor="order-quantity">{t("Quantity")} {t(wholeUnits?"(whole units)":"(base units)")}</label><span className="field-hint">{t("Held:")} {formatQuantity(held)}</span></div>
              <div className="quantity-field"><input id="order-quantity" type="number" inputMode="decimal" step={wholeUnits?"1":"any"} min={wholeUnits?"1":"0.00000001"} value={quantity} onChange={e=>{setQuantity(e.target.value);setTradeError("");}} required/><span>{t("UNITS")}</span></div>
              <div className="ticket-summary">
                <div><span>{t("Last reference price")}</span><strong>{snapshot==null?"—":formatPrice(snapshot, selectedAsset.decimals)}</strong></div>
                <div><span>{t(mode==="replay"?"Est. fill at current close":"Estimated fill price")}</span><strong>{indicativeFill == null?"—":formatPrice(indicativeFill, selectedAsset.decimals)}</strong></div>
                <div><span>{t(mode==="replay"?"Model spread":"Modeled spread")}</span><strong>{selectedAsset.spreadBps} bps</strong></div>
                <div className="ticket-total"><span>{t(mode==="replay"?"Illustrative order value":"Estimated order value")}</span><strong>{formatMoney(estimate)}</strong></div>
              </div>
              {replayAccount.pending && mode==="replay" && <p className="support-text">{t("Pending")} {t(replayAccount.pending.side)} {t("order for")} {formatQuantity(replayAccount.pending.quantity)} {t("units. Advance replay to fill.")}</p>}
              {tradeError && <p role="alert" className="form-error">{t(tradeError)}</p>}
              {!supported && <p className="support-text">{t(selectedAsset.assetClass==="Options"?"Choose a real dated contract in a future options-chain release.":selectedAsset.assetClass==="Futures"?"Chart-only until multiplier, margin, and settlement rules are implemented.":"CAD-to-USD conversion is not implemented.")}</p>}
              {supported && mode==="market" && !quoteReady && <p className="support-text">{t(quote?.block_reason ?? "No fresh market quote. Orders are blocked.")}</p>}
              <button type="submit" className={`submit-order ${side==="sell"?"submit-sell":""}`} disabled={!canTrade || placing}>
                {side==="buy"?<ArrowUpRight size={19}/>:<ArrowDownLeft size={19}/>}
                {placing?t("Submitting..."):mode==="replay"?`${t("Queue replay")} ${t(side)}`:`${t("Paper")} ${t(side)}`}
              </button>
            </form>
            <div className="ticket-footnote"><ShieldCheck size={15}/><span>{t("Long-only USD account. Market-mode orders require fresh quotes during supported sessions. Spread, slippage and fees are modeled, not guaranteed execution.")}</span></div>
          </section>
          <section className="account-card">
            <div className="account-heading"><span>{t("SIMULATION STATUS")}</span><span className="account-status"><span className={backendOnline?"local-dot":"offline-dot"}/>{t(backendOnline?"ONLINE":"OFFLINE")}</span></div>
            <div className="account-item"><Database size={17}/><div><strong>{t("Market data")}</strong><span>{history?.source ?? "Unavailable"}</span></div><span className="offline-tag">{t(history?"REAL":"NONE")}</span></div>
            <div className="account-item"><Clock3 size={17}/><div><strong>{t("Last quote")}</strong><span>{quote ? dt(quote.timestamp) : t("Unavailable")}</span></div></div>
            <div className="account-item">{mode==="replay"?<PauseCircle size={17}/>:<Check size={17}/>}<div><strong>{t(mode==="replay"?"Historical replay":"Quote freshness")}</strong><span>{t(mode==="replay"?"Step-by-step, next-open fills":quote?.fresh?"Fresh enough for paper model":"Stale or unavailable")}</span></div></div>
            <div className="account-item"><RefreshCw size={17}/><div><strong>{t("Market snapshots")}</strong><span>{t("Refresh quote roughly every 45 seconds")}</span></div>
              <button type="button" className="mini-icon-button" onClick={() => {void getQuote(selectedId).then(next=>{setQuote(next);setLastQuotes(p=>({...p,[selectedId]:next}));}).catch(e=>setMarketError(errorMessage(e)));}} title={t("Refresh quote")}><RefreshCw size={14}/></button>
            </div>
          </section>
          <div className="build-note"><span className="build-dot"/> {t("Trading Simulator")} <span>{t("v0.2 · LOCAL ENGINE")}</span></div>
        </aside>
      </div>
      {notice && <div className="toast" role="status"><Check size={17}/><span>{t(notice)}</span><button type="button" onClick={()=>setNotice("")} aria-label={t("Dismiss message")}><X size={16}/></button></div>}
    </div>
  );
}

