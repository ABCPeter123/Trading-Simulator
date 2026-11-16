import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import TradingArcade from "./TradingArcade";
import PortfolioArcade from "./PortfolioArcade";
import { I18nProvider, LanguageSwitcher } from "./i18n";
import "./styles.css";

function Root() {
  const [view, setView] = useState<"arcade"|"portfolio">("arcade");
  const content = view === "portfolio"
    ? <PortfolioArcade onExit={() => setView("arcade")}/>
    : <TradingArcade onOpenPortfolio={() => setView("portfolio")}/>;
  return <>{content}<LanguageSwitcher/></>;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><I18nProvider><Root/></I18nProvider></React.StrictMode>,
);
