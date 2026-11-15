import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import TradingArcade from "./TradingArcade";
import PortfolioArcade from "./PortfolioArcade";
import "./styles.css";

function Root() {
  const [view, setView] = useState<"terminal"|"arcade"|"portfolio">("arcade");
  if (view === "portfolio") {
    return <PortfolioArcade onExit={() => setView("arcade")}/>;
  }
  if (view === "arcade") {
    return <TradingArcade onExit={() => setView("terminal")} onOpenPortfolio={() => setView("portfolio")}/>;
  }
  return <App onOpenArcade={() => setView("arcade")}/>;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><Root/></React.StrictMode>,
);
