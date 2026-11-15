import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import TradingArcade from "./TradingArcade";
import "./styles.css";

function Root() {
  const [view, setView] = useState<"terminal"|"arcade">("arcade");
  return view === "arcade"
    ? <TradingArcade onExit={() => setView("terminal")}/>
    : <App onOpenArcade={() => setView("arcade")}/>;
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode><Root/></React.StrictMode>,
);
