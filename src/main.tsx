import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import TradingArcade from "./TradingArcade";
import PortfolioArcade from "./PortfolioArcade";
import { I18nProvider, LanguageSwitcher, useI18n } from "./i18n";
import "./styles.css";
import "./simulatorNavigation.css";
import "./mobile.css";

function Simulator() {
  const { t } = useI18n();
  const [mode, setMode] = useState<"single" | "portfolio">("single");
  return <>
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
    <LanguageSwitcher />
  </>;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><I18nProvider><Simulator /></I18nProvider></React.StrictMode>,
);
