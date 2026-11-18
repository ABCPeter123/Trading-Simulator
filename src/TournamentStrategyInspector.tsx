import {useEffect,useMemo,useState} from "react";
import {useI18n} from "./i18n";
import {modelDescription,getTournamentPythonSource} from "./tournamentApi";
import type {PythonStrategySource} from "./tournamentApi";
import "./tournamentInspector.css";

export interface TournamentModelSpec {
  version:1|2; model:string; symbols:string[];
  max_position_pct:number; delay_sessions:1|2; rebalance_sessions:number;
  restricted_research?:boolean; short_proxy_research?:boolean; research_only?:boolean;
}

type ResearchCosts = {
  commission_usd?:number; slippage_bps?:number;
  fx_conversion_bps?:number; base_currency?:string;
};

const modelRules:Record<string, string[]> = {
  equal_weight:[
    "For each eligible asset, set raw_weight = 1.",
    "Normalize across the basket, then apply the position and asset-class limits.",
  ],
  inverse_volatility:[
    "Calculate daily returns from the latest 60 completed sessions.",
    "Estimate volatility as max(sample_standard_deviation(returns), 0.002).",
    "Set raw_weight = 1 / volatility, then normalize and apply risk limits.",
  ],
  trend_filter:[
    "Calculate the 126-session simple average close for each asset.",
    "If the latest completed close is above its 126-session average, set raw_weight = 1 / volatility(60).",
    "Otherwise assign that asset a raw weight of 0; uninvested funds stay in cash.",
  ],
  relative_momentum:[
    "For each asset, score = 0.5 × (latest_close / close_64_sessions_ago − 1) + 0.5 × (latest_close / close_127_sessions_ago − 1).",
    "Rank the basket by this score. Retain the top max(2, ceil(number_of_assets / 3)) assets.",
    "Only positively scoring retained assets receive raw_weight = 1 / volatility(60). All others receive 0.",
  ],
  volatility_target:[
    "Start with raw_weight = 1 / volatility(60) for each asset.",
    "Use the last 60 daily returns to estimate the annualized volatility of that normalized basket.",
    "Set gross_exposure = min(95%, 12% / estimated_annualized_volatility), then apply risk limits.",
  ],
  defensive_rotation:[
    "Compare each equity's last completed close to its previous 126-session mean.",
    "If most equities have positive trends, hold trend-qualified equity exposure under an equity class cap.",
    "Otherwise, move allocation into actual observed bond and commodity assets. Unused allocation stays in cash.",
  ],
  diversified_risk_parity:[
    "Compute 60-session inverse volatility for each asset.",
    "Apply tighter class limits: equities 45%, bonds 30%, commodities 20%, real estate 12%, crypto 5%.",
  ],
  equity_hedge:[
    "Allocate using inverse volatility across equities, actual bond instruments and actual commodity instruments.",
    "Cap equity at 50%, bonds at 30% and commodities at 20%. Retain spare cash.",
  ],
  leveraged_trend:[
    "Identify equities with positive completed-close 126-session trends and positive 64/127-session momentum.",
    "Set long target exposure up to 135% of equity, subject to per-asset caps.",
    "Model borrowing interest, spreads, slippage, next-open fills and a 25% maintenance-margin liquidation trigger.",
  ],
  long_short_momentum:[
    "Rank equity momentum across the prior 64 and 127 sessions.",
    "Long the strongest third, short the weakest third; target up to 95% long and 45% short notional.",
    "Model negative shares, stock-borrow costs, borrowing interest and margin liquidation risk. Never submit a share short to Wealthsimple.",
  ],
  market_neutral:[
    "Rank equity momentum using previously completed 64/127-session returns.",
    "Long the strongest third and short the weakest third with about 65% notional on each side.",
    "Include short borrow fees and a maintenance-margin liquidation trigger. This is a synthetic research position, not an executable Wealthsimple share short.",
  ],
};


export default function TournamentStrategyInspector({
  spec,exactCode,costs,context="research",
}:{
  spec:TournamentModelSpec;exactCode?:string;costs?:ResearchCosts;
  context?:"research"|"simulation"|"live";
}){
  const {t}=useI18n();
  const [copyStatus,setCopyStatus]=useState("");
  const [source,setSource]=useState<PythonStrategySource|null>(null);
  const [sourceError,setSourceError]=useState("");
  const [loadingSource,setLoadingSource]=useState(true);
  // A stable fingerprint prevents duplicate requests for recreated prop objects.
  const sourceKey=JSON.stringify([
    spec.version,spec.model,spec.symbols,spec.max_position_pct,
    spec.delay_sessions,spec.rebalance_sessions,spec.research_only??false,
    spec.restricted_research??false,spec.short_proxy_research??false,
  ]);
  const code=useMemo(()=>{
    if(exactCode){
      try{
        const parsed:unknown=JSON.parse(exactCode);
        if(parsed&&typeof parsed==="object"&&!Array.isArray(parsed))
          return JSON.stringify(parsed,null,2);
      }catch{/* Invalid frozen configuration: show the available spec instead. */}
    }
    return JSON.stringify({
      version:spec.version,model:spec.model,symbols:spec.symbols,
      max_position_pct:spec.max_position_pct,delay_sessions:spec.delay_sessions,
      rebalance_sessions:spec.rebalance_sessions,
      restricted_research:spec.restricted_research??false,
      short_proxy_research:spec.short_proxy_research??false,
      research_only:spec.research_only??false,
    },null,2);
  },[sourceKey,exactCode]);
  useEffect(()=>{
    let active=true;
    setSource(null);setSourceError("");setLoadingSource(true);
    void getTournamentPythonSource({
      version:spec.version,model:spec.model,symbols:spec.symbols,
      max_position_pct:spec.max_position_pct,delay_sessions:spec.delay_sessions,
      rebalance_sessions:spec.rebalance_sessions,
      restricted_research:spec.restricted_research??false,
      short_proxy_research:spec.short_proxy_research??false,
      research_only:spec.research_only??false,
    },context).then(result=>{if(active)setSource(result);})
      .catch(error=>{if(active)setSourceError(error instanceof Error?error.message:String(error));})
      .finally(()=>{if(active)setLoadingSource(false);});
    return ()=>{active=false;};
  },[sourceKey,context]);
  const copy=(value:string)=>{
    if(!navigator.clipboard){
      setCopyStatus(t("Clipboard unavailable. Select and copy the code manually."));return;
    }
    void navigator.clipboard.writeText(value)
      .then(()=>setCopyStatus(t("Copied.")))
      .catch(()=>setCopyStatus(t("Clipboard unavailable. Select and copy the code manually.")));
  };
  const rules=modelRules[spec.model]??["No documented rules exist for this model."];
  const publicPath=spec.version===2?"advanced_portfolio_research.py":"portfolio_research.py";
  return <section className="tsi" aria-label={t("Strategy logic and source")}>
    <header className="tsi-header">
      <div><h4>{t("Strategy logic and source")}</h4><p>{t(modelDescription(spec.model))}</p></div>
      <a href={"https://github.com/ABCPeter123/Trading-Simulator/blob/main/backend/"+publicPath}
        target="_blank" rel="noreferrer">{t("View public engine repository")}</a>
    </header>
    <div className="tsi-fields">
      <div><small>{t("Research asset basket")}</small><strong>{spec.symbols.map(s=>s.toUpperCase()).join(" · ")}</strong></div>
      <div><small>{t("Single-asset cap")}</small><strong>{spec.max_position_pct}%</strong></div>
      <div><small>{t("Rebalance cadence")}</small><strong>{spec.rebalance_sessions} {t("common sessions")}</strong></div>
      <div><small>{t("Execution assumption")}</small><strong>{spec.delay_sessions} {t("session(s)")}</strong></div>
    </div>
    {spec.research_only&&<p className="tsi-note">{t("Research-only synthetic exposure: not deployable to the cash simulator or Wealthsimple live engine.")}</p>}
    {(spec.restricted_research||spec.short_proxy_research)&&
      <p className="tsi-note">{t("This basket includes leveraged or inverse ETFs. The result is for research and simulation only, not approved live monitoring.")}</p>}
    <h5>{t("Exact executable strategy source")}</h5>
    <p className="tsi-note">{t("The running private Python backend supplies these actual execution functions. They are not pseudocode. Copy a complete module to work with its dependencies inside the repository.")}</p>
    {loadingSource&&<p className="tsi-note" role="status">{t("Loading actual Python engine source...")}</p>}
    {sourceError&&<p className="tsi-note" role="alert">{t("Exact source unavailable")}: {sourceError}</p>}
    {source&&<>
      <div className="tsi-runtime">
        <span>{t("Active allocation entry point")}: <code>{source.entry_point}</code></span>
        <span>{t("Research fill engine")}: <code>{source.research_execution_entry_point}</code></span>
        <span>{t("Execution context")}: {t(context)}</span>
      </div>
      {source.sections.map((section,index)=><details className="tsi-code" key={section.label+section.path} open={index===0}>
        <summary>{t(section.label)}</summary>
        <div className="tsi-code-actions">
          <span><code>{section.path}:{section.first_line}</code> · SHA-256 {section.sha256.slice(0,16)}</span>
          <button type="button" onClick={()=>copy(section.code)}>{t("Copy exact Python")}</button>
        </div>
        <pre>{section.code}</pre>
      </details>)}
      <details className="tsi-code">
        <summary>{t("Complete executable Python modules")}</summary>
        <p className="tsi-note">{t("These are complete files from the active backend, including imports, constants and helper functions.")}</p>
        {source.files.map(file=><details className="tsi-code tsi-module" key={file.path}>
          <summary>{file.path}</summary>
          <div className="tsi-code-actions">
            <span>SHA-256 {file.sha256}</span>
            <button type="button" onClick={()=>copy(file.code)}>{t("Copy full Python module")}</button>
          </div>
          <pre>{file.code}</pre>
        </details>)}
      </details>
    </>}
    <h5>{t("Strategy rules explained")}</h5>
    <ol className="tsi-rules">
      {rules.map((line,i)=><li key={i}>{t(line)}</li>)}
      <li>{t("The research backtest models next-open fills. The historical replay and live monitoring use separate execution and accounting paths.")}</li>
    </ol>
    {context==="simulation"&&<p className="tsi-note">{t("Historical replay uses the same target-weight function as tournament research, but its fill and fee approximation is different. Results may not match the tournament backtest exactly.")}</p>}
    {context==="live"&&<p className="tsi-note">{t("Live monitoring generates suggested order sizes from saved capital, current prices and confirmed fills. It does not read brokerage balances or place orders.")}</p>}
    {costs&&<p className="tsi-note">{t("Tournament research cost assumptions")}: {costs.slippage_bps??"?"} bps {t("slippage")}, {costs.commission_usd??"?"} USD {t("commission")}, {costs.fx_conversion_bps??"?"} bps {t("FX conversion")}, {costs.base_currency??"USD"} {t("base currency")}.</p>}
    <details className="tsi-code">
      <summary>{t("Versioned strategy parameters (JSON)")}</summary>
      <div className="tsi-code-actions">
        <span>{t("This JSON selects the real engine function and parameters. It is configuration, not standalone executable code.")}</span>
        <button type="button" onClick={()=>copy(code)}>{t("Copy JSON")}</button>
      </div>
      <pre>{code}</pre>
    </details>
    {copyStatus&&<p className="tsi-copy-status" role="status">{copyStatus}</p>}
  </section>;
}
