import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import TradingArcade from "./TradingArcade";
import PortfolioArcade from "./PortfolioArcade";
import CloudGateway from "./CloudGateway";
import LiveOperations from "./LiveOperations";
import StrategyDiscovery from "./StrategyDiscovery";
import MarketDesk from "./MarketDesk";
import UniverseResearch from "./UniverseResearch";
import type {OperationsSection} from "./LiveOperations";
import type {Signal} from "./liveMachineApi";
import {cloudFrontend, disconnectPrivateEngine, hasPrivateConnection} from "./privateConnection";
import { I18nProvider, LanguageSwitcher, useI18n } from "./i18n";
import "./styles.css";
import "./simulatorNavigation.css";
import "./mobile.css";
import "./polish.css";

function Simulator() {
  const { t } = useI18n();
  useEffect(()=>{
    if (import.meta.env.VITE_PUBLIC_DEMO === "1" || cloudFrontend) return;
    // Local-only and non-blocking. Retry startup races when the Python API
    // launches after Vite, without polling or contacting a cloud service.
    let cancelled=false;
    let retry:ReturnType<typeof setTimeout>|undefined;
    let attempts=0;
    const preload=()=>{
      attempts++;
      void fetch("/api/ai/warmup",{method:"POST"})
        .then(response=>{if(!response.ok)throw new Error("API not ready");})
        .catch(()=>{
          if(!cancelled&&attempts<6)retry=setTimeout(preload,4000);
        });
    };
    preload();
    return ()=>{cancelled=true;if(retry)clearTimeout(retry);};
  },[]);

  const [section,setSection]=useState<"research"|"live">(import.meta.env.VITE_PUBLIC_DEMO==="1"?"research":"research");
  const [researchSection,setResearchSection]=useState<"single"|"portfolio"|"discovery"|"tournament">("tournament");
  const [liveSection,setLiveSection]=useState<OperationsSection|"market">("dashboard");
  const [privateConnected,setPrivateConnected] = useState(hasPrivateConnection());
  const [preparedSignal,setPreparedSignal] = useState<Signal|null>(null);
  const [tournamentReplayId,setTournamentReplayId]=useState<string|undefined>(undefined);
  const [preferredLiveStrategy,setPreferredLiveStrategy]=useState<string|undefined>(undefined);
  if(cloudFrontend && !privateConnected) return <><CloudGateway onConnected={()=>setPrivateConnected(true)}/><LanguageSwitcher/></>;
  return <>
    {cloudFrontend && <div className="cloud-engine-bar" role="status">
      <span>{t("Private engine connected. Trading data remains on your PC.")}</span>
      <button type="button" onClick={()=>{disconnectPrivateEngine();setPrivateConnected(false);}}>
        {t("Disconnect private engine")}
      </button>
    </div>}
    {import.meta.env.VITE_PUBLIC_DEMO === "1" &&
      <div className="public-demo-banner" role="status">
        {t("PUBLIC DEMO · Shared sandbox. Never enter your private strategy, credentials, or actual financial data. Visitors may see each other's demo sessions.")}
      </div>}
    {import.meta.env.VITE_PUBLIC_DEMO !== "1" && <nav className="ops-main-tabs" aria-label={t("Application sections")}>
      <span className="ops-tab-brand">{t("Trading Simulator")}</span>
      {([["research","Research Lab"],["live","Live Engine"]] as const)
        .map(([id,label])=><button type="button" key={id} className={section===id?"active":""}
          aria-current={section===id?"page":undefined} onClick={()=>setSection(id)}>{t(label)}</button>)}
    </nav>}
    {section==="research" || import.meta.env.VITE_PUBLIC_DEMO==="1" ? <>
      {import.meta.env.VITE_PUBLIC_DEMO !== "1" && <nav className="sim-mode-tabs" aria-label={t("Research Workspaces")}>
        <span className="sim-mode-title">{t("Research Workspaces")}</span>
        {([["tournament","Strategy Tournament"],["single","Single-asset Research"],
          ["portfolio","Portfolio Research"],["discovery","Optimization & Discovery"]] as const)
          .map(([id,label])=><button key={id} type="button"
            className={researchSection===id?"selected":""}
            aria-current={researchSection===id?"page":undefined}
            onClick={()=>setResearchSection(id)}>{t(label)}</button>)}
      </nav>}
      {import.meta.env.VITE_PUBLIC_DEMO==="1" || researchSection==="single" ?
        <TradingArcade onOpenPortfolio={()=>setResearchSection("portfolio")}/>:
       researchSection==="portfolio"?
        <PortfolioArcade onExit={()=>setResearchSection("single")} initialRunId={tournamentReplayId}/>:
       researchSection==="discovery"?<StrategyDiscovery/>:
        <UniverseResearch onOpenDiscovery={()=>setResearchSection("discovery")}
          onOpenSimulation={id=>{setTournamentReplayId(id);setResearchSection("portfolio");}}
          onOpenLive={id=>{setPreferredLiveStrategy(id);setLiveSection("machine");setSection("live");}}/>}
    </> : <>
      <nav className="sim-mode-tabs" aria-label={t("Live Engine sections")}>
        <span className="sim-mode-title">{t("Live Engine")}</span>
        {([["dashboard","Overview & Actions"],["market","Live Data & Coverage"],
          ["machine","Strategy Engine"],["journal","Execution History"],
          ["alerts","Alerts & Health"]] as const)
          .map(([id,label])=><button key={id} type="button" className={liveSection===id?"selected":""}
            aria-current={liveSection===id?"page":undefined}
            onClick={()=>setLiveSection(id)}>{t(label)}</button>)}
      </nav>
      {liveSection==="market"?<main className="arc-page"><MarketDesk/></main>:
       <LiveOperations section={liveSection} initialSignal={preparedSignal}
        preferredStrategyId={preferredLiveStrategy}
        onOpenResearch={()=>{setSection("research");setResearchSection("tournament");}}
        onRecordSignal={signal=>{setPreparedSignal(signal);setLiveSection("journal");}}
        onConsumed={()=>setPreparedSignal(null)}/>}
    </>}

    <LanguageSwitcher/>
  </>;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><I18nProvider><Simulator /></I18nProvider></React.StrictMode>,
);
