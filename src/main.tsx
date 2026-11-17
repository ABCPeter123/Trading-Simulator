import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import TradingArcade from "./TradingArcade";
import PortfolioArcade from "./PortfolioArcade";
import { I18nProvider, LanguageSwitcher, useI18n } from "./i18n";
import "./styles.css";
import "./simulatorNavigation.css";
import "./mobile.css";
import "./polish.css";

function Simulator() {
  const { t } = useI18n();
  useEffect(()=>{
    if (import.meta.env.VITE_PUBLIC_DEMO === "1") return;
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
  const [mode, setMode] = useState<"single" | "portfolio">("single");
  return <>
    {import.meta.env.VITE_PUBLIC_DEMO === "1" &&
      <div className="public-demo-banner" role="status">
        {t("PUBLIC DEMO · Shared sandbox. Never enter your private strategy, credentials, or actual financial data. Visitors may see each other's demo sessions.")}
      </div>}
    <nav className="sim-mode-tabs" aria-label={t("Simulation mode")}>
      <span className="sim-mode-title">{t("Trading Simulator")}</span>
      <button type="button" className={mode === "single" ? "selected" : ""}
        aria-current={mode === "single" ? "page" : undefined}
        onClick={() => setMode("single")}>{t("Single-asset research")}</button>
      <button type="button" className={mode === "portfolio" ? "selected" : ""}
        aria-current={mode === "portfolio" ? "page" : undefined}
        onClick={() => setMode("portfolio")}>{t("Portfolio Simulator")}</button>
    </nav>
    {mode === "portfolio"
      ? <PortfolioArcade onExit={() => setMode("single")} />
      : <TradingArcade onOpenPortfolio={() => setMode("portfolio")} />}
    <LanguageSwitcher/>
  </>;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><I18nProvider><Simulator /></I18nProvider></React.StrictMode>,
);
