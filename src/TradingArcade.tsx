import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity, ArrowDownRight, ArrowLeft, ArrowUpRight, Award, Bot, Check,
  ChevronRight, Clock3, Code2, FastForward, Flag, Gauge, Medal, Pause,
  Play, Plus, Save, ShieldCheck, Sparkles, Target, Terminal,
  Trash2, Trophy, Wallet, Zap,
} from "lucide-react";
import { ASSETS, formatMoney, formatPrice } from "./data/demoMarket";
import { PriceChart } from "./components/PriceChart";
import {
  gameCancel, gameLoad, gameRuns, gameSaveCode, gameStart, gameStep,
  gameTrade, gameValidateCode,
} from "./arcadeApi";
import type { ArcadeRun, OrderKind, SavedArcadeRun } from "./arcadeApi";
import type { TradeSide } from "./types";
import "./arcade.css";

const SAVED_KEY = "trading-simulator-arcade-current-run";
const ELIGIBLE = ASSETS.filter(a => !["Futures","Options"].includes(a.assetClass) && a.id !== "vfv");
const QUICK_SIZES = [10, 25, 50, 100];
const asTime = (seconds: number) => new Date(seconds*1000).toLocaleDateString("en-CA", {year:"numeric",month:"short",day:"numeric"});
const errText = (error: unknown) => error instanceof Error ? error.message : "An unexpected error occurred.";
const SAMPLE_CODE = "WHEN SMA(10) CROSSES ABOVE SMA(30) BUY 50%\nWHEN SMA(10) CROSSES BELOW SMA(30) SELL 100%";

function Metric({label, value, note, positive}: {label: string; value: string; note?: string; positive?: boolean}) {
  return <div className="arc-metric"><span>{label}</span><strong className={positive===undefined?"":positive?"positive":"negative"}>{value}</strong>{note && <small>{note}</small>}</div>;
}

export default function TradingArcade({onExit}: {onExit:()=>void}) {
  const [game, setGame] = useState<ArcadeRun|null>(null);
  const [saved, setSaved] = useState<SavedArcadeRun[]>([]);
  const [assetId, setAssetId] = useState("aapl");
  const [startingPoint, setStartingPoint] = useState(0.3);
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

  const load = useCallback(async (id: string) => {
    const run = await gameLoad(id);
    setGame(run);
    setCode(run.strategy || SAMPLE_CODE);
    setNewGame(false);
    setError("");
    localStorage.setItem(SAVED_KEY, id);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const boot = async () => {
      try {
        const runs = await gameRuns();
        if (cancelled) return;
        setSaved(runs);
        const stored = localStorage.getItem(SAVED_KEY);
        const resume = runs.find(r=>r.id===stored) ?? runs[0];
        if (resume) {
          try {
            const state = await gameLoad(resume.id);
            if (!cancelled) {setGame(state);setCode(state.strategy || SAMPLE_CODE);localStorage.setItem(SAVED_KEY,resume.id);}
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

  async function createNew() {
    setPlaying(false);
    if(busyRef.current)return;
    busyRef.current=true;setBusy(true);setError("");
    try {
      const result=await gameStart(assetId,startingPoint);
      setGame(result);
      setCode(SAMPLE_CODE);
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

  const asset=ASSETS.find(a=>a.id===game?.asset_id);
  const latest=game?.bars.at(-1);
  const q=game?.metrics;
  const delta=latest&&game&&game.bars.length>=2 ? latest.close-game.bars[game.bars.length-2].close : 0;
  const codeSaved=game?.strategy===code;

  return <div className="arc-page">
    <header className="arc-top">
      <div className="arc-top-left">
        <button className="arc-back" title="Back to trading terminal" onClick={()=>{setPlaying(false);onExit();}}><ArrowLeft size={18}/></button>
        <div className="arc-logo"><Zap size={23} fill="currentColor"/></div>
        <div className="arc-brand">TRADING <span>ARCADE</span><small>MARKET REPLAY · STRATEGY LAB</small></div>
      </div>
      <div className="arc-top-right">
        <span className="arc-live"><span/> LOCAL HISTORICAL GAME</span>
        {q && <div className="arc-player"><div className="arc-avatar"><Trophy size={17}/></div><div><strong>LEVEL {q.level}</strong><span>{q.xp} XP · {q.score.toLocaleString()} score</span></div></div>}
        <button className="arc-outline-button" onClick={()=>{setPlaying(false);setNewGame(true);setError("");}}><Plus size={15}/> New season</button>
      </div>
    </header>

    {initializing ? <div className="arc-intro"><Activity className="spin" size={30}/><h2>Loading your arcade</h2><p>Reading local game saves.</p></div> :
     newGame || !game ? <main className="arc-intro">
       <div className="arc-intro-icon"><Trophy size={35}/></div>
       <span className="arc-upper">WELCOME TO THE MARKET</span>
       <h1>Trade through history.<br/><em>Beat the market.</em></h1>
       <p>Start with $100,000 in virtual cash, reveal real historical candles, and compete against buy-and-hold. Play manually or design a trading bot. Skip weeks in seconds.</p>
       <div className="arc-start-form">
         <label htmlFor="arc-new-asset">Choose your market</label>
         <select id="arc-new-asset" value={assetId} onChange={e=>setAssetId(e.target.value)}>
           {ELIGIBLE.map(a=><option key={a.id} value={a.id}>{a.symbol} · {a.name}</option>)}
         </select>
         <label htmlFor="arc-start-point">Starting point</label>
         <select id="arc-start-point" value={startingPoint} onChange={e=>setStartingPoint(Number(e.target.value))}>
           <option value={0.2}>Early season · More candles to play</option>
           <option value={0.3}>Standard season</option>
           <option value={0.5}>Quick season</option>
         </select>
         <button disabled={busy} className="arc-cta" onClick={()=>void createNew()}><Play size={18} fill="currentColor"/>{busy?"Loading market data...":"Start trading"}</button>
         {saved.length>0 && <><span className="arc-resume-title">OR RESUME A SAVED SEASON</span><select aria-label="Resume a saved arcade run" defaultValue="" onChange={e=>{if(e.target.value)void switchRun(e.target.value);}}><option value="">Select a previous run...</option>{saved.map(run=><option key={run.id} value={run.id}>{ASSETS.find(a=>a.id===run.asset_id)?.symbol} · {new Date(run.updated_at).toLocaleString()}</option>)}</select></>}
         {error && <div className="arc-error" role="alert">{error}</div>}
       </div>
       <div className="arc-intro-foot"><ShieldCheck size={15}/> Uses actual historical candles when available. All trading is simulated.</div>
     </main> : <main className="arc-layout">
       <div className="arc-main">
         <section className="arc-hero">
           <div className="arc-symbol-line">
             <div><span className="arc-upper">SEASON IN PROGRESS</span><h1>{asset?.symbol??game.asset_id}<span className="arc-symbol-currency"> / USD</span></h1><p>{asset?.name} · {game.source}</p></div>
             <div className="arc-price"><strong>{latest ? formatPrice(latest.close,asset?.decimals??2):"—"}</strong><span className={delta>=0?"positive":"negative"}>{delta>=0?<ArrowUpRight size={15}/>:<ArrowDownRight size={15}/>} {delta>=0?"+":""}{formatPrice(delta,asset?.decimals??2)} last candle</span></div>
           </div>
           <div className="arc-progress-line">
             <div><span><Clock3 size={13}/> {latest?asTime(latest.time):"—"}</span><span>{game.current_bar+1} of {game.total_bars} candles revealed</span><span>{game.progress_pct.toFixed(1)}% complete</span></div>
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
           <div className="arc-box-head"><div><Activity size={17}/><strong>Historical market</strong><span className="arc-tag">FUTURE HIDDEN</span></div><div className="arc-chart-view"><button className={chartStyle==="candles"?"selected":""} onClick={()=>setChartStyle("candles")}>Candles</button><button className={chartStyle==="line"?"selected":""} onClick={()=>setChartStyle("line")}>Line</button></div></div>
           <div className="arc-chart-wrap"><PriceChart asset={asset!} range="1Y" style={chartStyle} bars={game.bars}/></div>
           <div className="arc-chart-bottom"><span><span className="arc-green-dot"/> REAL HISTORICAL OHLCV</span><span>Next candle cannot be viewed until you advance</span></div>
         </section>

         <section className="arc-time-panel">
           <div className="arc-box-head"><div><FastForward size={17}/><strong>Time machine</strong><span className="arc-tag">NO WAITING</span></div>{game.finished&&<span className="arc-complete"><Flag size={14}/> SEASON FINISHED</span>}</div>
           <p>Every step advances the historical market, checks your pending orders, and executes active strategy rules. No real-time waiting.</p>
           <div className="arc-time-actions">
             <button disabled={busy||playing||game.finished} onClick={()=>void action(()=>gameStep(game.id,1))}><ChevronRight size={17}/> Next candle</button>
             <button disabled={busy||playing||game.finished} onClick={()=>void action(()=>gameStep(game.id,5))}><FastForward size={15}/> +5 candles</button>
             <button disabled={busy||playing||game.finished} onClick={()=>void action(()=>gameStep(game.id,20))}><FastForward size={16}/> +20 candles</button>
             <button disabled={busy||playing||game.finished||!game.strategy.trim()} onClick={()=>void action(()=>gameStep(game.id,100,true))}><Target size={16}/> Next bot action</button>
           </div>
           <div className="arc-auto">
             <div><strong><Gauge size={16}/> Autoplay</strong><span>Automatically reveal history while you watch.</span></div>
             <select aria-label="Autoplay step speed" value={speed} onChange={e=>setSpeed(Number(e.target.value))}><option value={1}>1 bar / tick</option><option value={5}>5 bars / tick</option><option value={10}>10 bars / tick</option></select>
             <button className={playing?"arc-playing":""} disabled={game.finished} onClick={()=>setPlaying(p=>!p)}>{playing?<><Pause size={15}/> Pause</>:<><Play size={15}/> Play</>}</button>
           </div>
         </section>

         <section className="arc-bot-section">
           <div className="arc-box-head"><div><Bot size={18}/><strong>Strategy Workshop</strong><span className="arc-tag">NO CODING EXPERIENCE NEEDED</span></div><button className="arc-subtle-button" onClick={()=>setEditorOpen(v=>!v)}>{editorOpen?"Collapse":"Expand"}</button></div>
           <div className="arc-bot-summary"><div className="arc-bot-icon"><Code2 size={21}/></div><div><strong>Teach your trading bot what to do</strong><p>Write rules in plain English. The engine evaluates the conditions at each revealed candle close, then queues trades for the next candle.</p></div></div>
           {editorOpen&&<div className="arc-editor">
             <div className="arc-template-row"><span>TRY A TEMPLATE</span>{game.examples.map(sample=><button key={sample.title} onClick={()=>{setCode(sample.code);setCodeError("");}}>{sample.title}</button>)}</div>
             <div className="arc-code-head"><span><Terminal size={14}/> strategy.tradesim</span><span>{codeSaved?"SAVED TO GAME":"UNSAVED CHANGES"}</span></div>
             <textarea spellCheck={false} aria-label="Trading strategy rules" value={code} onChange={e=>{setCode(e.target.value);setCodeError("");}} rows={5} placeholder="WHEN SMA(10) CROSSES ABOVE SMA(30) BUY 25%" maxLength={1800}/>
             <div className="arc-editor-help">
               <strong>Language cheatsheet</strong>
               <p><code>WHEN SMA(10) CROSSES ABOVE SMA(30) BUY 25%</code> · <code>WHEN RSI(14) BELOW 30 BUY 25%</code></p>
               <p>Indicators: PRICE, SMA(2-100), RSI(2-100). Conditions: ABOVE, BELOW, CROSSES ABOVE, CROSSES BELOW. Trades: BUY or SELL a percentage.</p>
               <p>BUY % uses available cash. SELL % uses holdings. Rules trigger on crossing events, not every candle. No Python code or unsafe execution.</p>
             </div>
             {codeError&&<div role="alert" className="arc-error">{codeError}</div>}
             <div className="arc-code-actions"><span>{game.strategy.trim()?"Bot armed":"No active strategy yet"}</span><button disabled={busy||validating||codeSaved} onClick={()=>void saveCode()}><Save size={15}/>{validating?"Validating...":"Save & arm bot"}</button></div>
           </div>}
         </section>

         <section className="arc-history">
           <div className="arc-box-head"><div><Clock3 size={17}/><strong>Trade journal</strong><span className="arc-tag">{game.fills.length} RECENT FILLS</span></div></div>
           {game.fills.length?<div className="arc-table-scroll"><table><thead><tr><th>DATE</th><th>SIDE</th><th>TYPE</th><th>QTY</th><th>PRICE</th><th>FEE</th></tr></thead><tbody>{game.fills.slice(0,20).map((fill,index)=><tr key={fill.order_id+"-"+index}><td>{asTime(fill.time)}</td><td className={fill.side==="buy"?"positive":"negative"}>{fill.side.toUpperCase()}</td><td>{fill.source==="bot"?"BOT · ":""}{fill.kind}</td><td>{fill.quantity.toLocaleString("en-US",{maximumFractionDigits:8})}</td><td>{formatPrice(fill.price,asset?.decimals??2)}</td><td>{formatMoney(fill.fee)}</td></tr>)}</tbody></table></div>
             : <div className="arc-empty">No fills yet. Place a trade, then advance the timeline.</div>}
         </section>
       </div>

       <aside className="arc-side">
         <section className="arc-level-card">
           <div className="arc-level-head"><Medal size={17}/><span>TRADER RANK</span><strong>LVL {q!.level}</strong></div>
           <h2>{q!.score.toLocaleString()} <small>POINTS</small></h2>
           <p>Measured against buy-and-hold with a drawdown penalty.</p>
           <div className="arc-xp-track"><div style={{width:`${q!.xp%125/125*100}%`}}/></div>
           <span>{q!.xp%125} / 125 XP to next level</span>
           <div className="arc-badges">{q!.badges.map(b=><div key={b}><Award size={13}/>{b}</div>)}{!q!.badges.length&&<small>Place your first fill to earn a badge.</small>}</div>
         </section>

         <section className="arc-trade-card">
           <div className="arc-box-head"><div><Wallet size={17}/><strong>Trade desk</strong></div><span className="arc-tag">PAPER MONEY</span></div>
           <div className="arc-side-body">
             <div className="arc-side-toggle"><button className={side==="buy"?"active-buy":""} onClick={()=>setSide("buy")}><ArrowUpRight size={16}/> Buy</button><button className={side==="sell"?"active-sell":""} onClick={()=>setSide("sell")}><ArrowDownRight size={16}/> Sell</button></div>
             <form onSubmit={e=>void placeOrder(e)}>
               <label htmlFor="arc-order-kind">Order type</label>
               <select id="arc-order-kind" value={orderKind} onChange={e=>setOrderKind(e.target.value as OrderKind)}>
                 <option value="market">Market · next open</option><option value="limit">Limit · favorable price</option><option value="stop">Stop · triggered price</option>
               </select>
               {orderKind!=="market"&&<><label htmlFor="arc-trigger">Trigger price (USD)</label><input id="arc-trigger" inputMode="decimal" type="number" step="any" min="0.000001" value={price} onChange={e=>setPrice(e.target.value)} required placeholder={latest?.close.toFixed(asset?.decimals??2)}/></>}
               <div className="arc-field-row"><label htmlFor="arc-size">Position size</label><select aria-label="Amount type" value={sizeMode} onChange={e=>{setSizeMode(e.target.value as "percent"|"units");setSize("25");}}><option value="percent">Percent</option><option value="units">Units</option></select></div>
               <div className="arc-size-wrap"><input id="arc-size" type="number" min="0.00000001" step="any" value={size} onChange={e=>setSize(e.target.value)} required/><span>{sizeMode==="percent"?"%":"UNITS"}</span></div>
               {sizeMode==="percent"&&<div className="arc-size-presets">{QUICK_SIZES.map(n=><button type="button" key={n} className={Number(size)===n?"chosen":""} onClick={()=>setSize(String(n))}>{n}%</button>)}</div>}
               <div className="arc-quote-mini"><span>Last candle close</span><strong>{latest?formatPrice(latest.close,asset?.decimals??2):"—"}</strong></div>
               <div className="arc-quote-mini"><span>Units held</span><strong>{q!.quantity.toLocaleString("en-US",{maximumFractionDigits:8})}</strong></div>
               <div className="arc-quote-mini"><span>Cash available</span><strong>{formatMoney(q!.cash)}</strong></div>
               <button className={side==="buy"?"arc-buy-cta":"arc-sell-cta"} disabled={busy||playing||game.finished} type="submit">{side==="buy"?<ArrowUpRight size={17}/>:<ArrowDownRight size={17}/>} Queue {side.toUpperCase()} order</button>
             </form>
             <div className="arc-disclaimer"><ShieldCheck size={14}/><span>Orders execute only as new candles reveal. Fees, spread and slippage are modeled.</span></div>
           </div>
         </section>

         <section className="arc-pending-card">
           <div className="arc-box-head"><div><Target size={16}/><strong>Pending orders</strong></div><span className="arc-tag">{game.orders.length}</span></div>
           {game.orders.length?game.orders.map(order=><div className="arc-pending" key={order.id}>
             <div><strong className={order.side==="buy"?"positive":"negative"}>{order.side.toUpperCase()} {order.size}{order.size_type==="percent"?"%":" units"}</strong><span>{order.kind.toUpperCase()}{order.price?" @ "+order.price:""} · {order.source}</span></div>
             <button title="Cancel pending order" disabled={busy||playing} onClick={()=>void action(()=>gameCancel(game.id,order.id))}><Trash2 size={15}/></button>
           </div>):<div className="arc-empty">No pending orders.</div>}
         </section>

         <section className="arc-events">
           <div className="arc-box-head"><div><Sparkles size={17}/><strong>Activity feed</strong></div></div>
           {game.events.slice(0,6).map((event,i)=><p key={i}><span className="arc-feed-dot"/>{event}</p>)}
         </section>
         {error&&<div role="alert" className="arc-error arc-floating-error">{error}<button onClick={()=>setError("")} aria-label="Dismiss error">Dismiss</button></div>}
         {note&&!error&&<div role="status" className="arc-note"><Check size={15}/>{note}<button onClick={()=>setNote("")} aria-label="Dismiss note">×</button></div>}
       </aside>
     </main>}
     <footer className="arc-footer"><span>Trading Arcade · local-first historical market simulation</span><span>Bar-level approximations, not live exchange executions</span></footer>
  </div>;
}
