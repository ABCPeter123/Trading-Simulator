import {useMemo,useState} from "react";
import type {FormEvent} from "react";
import {Activity,ArrowRight,Cloud,Database,KeyRound,LockKeyhole,ShieldCheck,WifiOff} from "lucide-react";
import {PriceChart} from "./components/PriceChart";
import {ASSETS} from "./data/demoMarket";
import type {MarketBar} from "./api";
import {connectPrivateEngine} from "./privateConnection";
import {useI18n} from "./i18n";
import "./cloudGateway.css";

function sampleData():MarketBar[]{
  // Illustrative deterministic synthetic series. Never use private historical
  // returns, stored strategies or portfolios to populate the hosted bundle.
  let seed=2147,price=100;
  const bars:MarketBar[]=[];
  const date=new Date("2024-01-02T00:00:00Z");
  for(let i=0;bars.length<450;i++){
    const dt=new Date(date.getTime()+i*86400000);
    if(dt.getUTCDay()===0||dt.getUTCDay()===6)continue;
    seed=(Math.imul(seed,1664525)+1013904223)>>>0;
    const swing=((seed/4294967296)-.48)*.048;
    const open=price;
    price=Math.max(15,price*(1+swing));
    bars.push({
      time:Math.floor(dt.getTime()/1000),open,close:price,
      high:Math.max(open,price)*1.008,low:Math.min(open,price)*.992,
      volume:100000+seed%1200000,
    });
  }
  return bars;
}

export default function CloudGateway({onConnected}:{onConnected:()=>void}){
  const {t}=useI18n();
  const [origin,setOrigin]=useState("");
  const [token,setToken]=useState("");
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState("");
  const bars=useMemo(sampleData,[]);
  async function submit(e:FormEvent){
    e.preventDefault();setBusy(true);setMessage("");
    try{
      await connectPrivateEngine(origin,token);
      setToken("");onConnected();
    }catch(err){setMessage(err instanceof Error?err.message:String(err));}
    finally{setBusy(false);}
  }
  return <div className="cloud-gateway">
    <header className="cloud-gateway-top">
      <div className="cloud-gateway-mark"><Activity size={23}/><strong>Trading Simulator</strong></div>
      <div className="cloud-gateway-status"><LockKeyhole size={14}/>{t("Frontend only · Private by default")}</div>
    </header>
    <main className="cloud-gateway-content">
      <section className="cloud-gateway-hero">
        <div className="cloud-gateway-kicker">{t("QUANTITATIVE RESEARCH WORKSPACE")}</div>
        <h1>{t("Your trading research. Your data.")}</h1>
        <p>{t("The website runs on Vercel. Strategies, models, historical databases and actual trading records stay on your computer. Connect your private engine to unlock the full workspace.")}</p>
        <div className="cloud-gateway-principles">
          <span><Cloud size={17}/>{t("Website on Vercel")}</span>
          <span><Database size={17}/>{t("Research stored locally")}</span>
          <span><ShieldCheck size={17}/>{t("No shared trading account")}</span>
        </div>
      </section>
      <div className="cloud-gateway-grid">
        <section className="cloud-gateway-connect" aria-label={t("Connect private engine")}>
          <div className="cloud-gateway-section-icon"><KeyRound size={19}/></div>
          <h2>{t("Connect private engine")}</h2>
          <p>{t("Your local Python service provides the trading data and calculations. The browser never sends an access token to Vercel.")}</p>
          <form onSubmit={e=>void submit(e)}>
            <label>{t("Engine URL")}
              <input type="url" value={origin} onChange={e=>setOrigin(e.target.value)}
                placeholder="https://your-private-tunnel.trycloudflare.com"
                autoComplete="off" spellCheck={false} required/>
            </label>
            <label>{t("Private access token")}
              <input type="password" value={token} onChange={e=>setToken(e.target.value)}
                placeholder={t("Paste the token from your private bridge terminal")}
                autoComplete="off" minLength={48} required/>
            </label>
            {message&&<p className="cloud-gateway-error" role="alert">{message}</p>}
            <button disabled={busy} type="submit">{busy?t("Connecting..."):t("Open trading workspace")}<ArrowRight size={17}/></button>
          </form>
          <div className="cloud-gateway-help">
            <WifiOff size={17}/><div>
              <strong>{t("No engine running yet?")}</strong>
              <p>{t("Start the private bridge on your Windows PC. Then copy its temporary HTTPS address and access token here. The PC must stay online.")}</p>
              <code>powershell -ExecutionPolicy Bypass -File .\start-private-bridge.ps1 -AllowedOrigin "{typeof window!=="undefined"?window.location.origin:"https://your-site.vercel.app"}"</code>
            </div>
          </div>
        </section>
        <section className="cloud-gateway-preview">
          <div className="cloud-gateway-preview-head"><div><span>{t("INTERFACE PREVIEW")}</span><h2>{t("Historical research chart")}</h2></div>
            <span className="cloud-gateway-demo-label">{t("SYNTHETIC EXAMPLE")}</span></div>
          <div className="cloud-gateway-chart"><PriceChart asset={ASSETS[4]} range="1Y" style="candles" bars={bars} smaPeriods={[20,50]}/></div>
          <p>{t("Illustrative synthetic candles only. No live market prices, real trading signals or private strategy information are published here.")}</p>
        </section>
      </div>
      <footer className="cloud-gateway-footer">{t("Static frontend only. No trading backend, database, or AI model is deployed to Vercel.")}</footer>
    </main>
  </div>;
}
