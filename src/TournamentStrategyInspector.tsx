import {useMemo,useState} from "react";
import {useI18n} from "./i18n";
import {modelDescription} from "./tournamentApi";
import "./tournamentInspector.css";

export interface TournamentModelSpec {
  version:1;
  model:string;
  symbols:string[];
  max_position_pct:number;
  delay_sessions:1|2;
  rebalance_sessions:number;
  restricted_research?:boolean;
  short_proxy_research?:boolean;
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
};

const sourceLink="https://github.com/ABCPeter123/Trading-Simulator/blob/main/backend/portfolio_research.py#L186-L235";
const groupCaps:[string,number][]=[["Equities",70],["Bonds",55],["Commodities",35],["Real estate",20],["Crypto",10]];

function algorithmFor(spec:TournamentModelSpec):string {
  const modelLines:Record<string,string[]> = {
    equal_weight:["raw[asset] = 1 for every asset"],
    inverse_volatility:["raw[asset] = 1 / max(stdev(last_60_daily_returns), 0.002)"],
    trend_filter:[
      "raw[asset] = (1 / volatility_60) if last_close > mean(last_126_closes) else 0",
    ],
    relative_momentum:[
      "momentum[asset] = 0.5 * (last_close / close_at_i_minus_64 - 1)",
      "                + 0.5 * (last_close / close_at_i_minus_127 - 1)",
      "selected = top max(2, ceil(asset_count / 3)) assets by momentum",
      "raw[asset] = 1 / volatility_60 if asset in selected and momentum > 0 else 0",
    ],
    volatility_target:[
      "raw[asset] = 1 / max(stdev(last_60_daily_returns), 0.002)",
      "estimated_risk = stdev(last_60_weighted_portfolio_returns) * sqrt(252)",
      "gross = 0.95",
      "if length(recent_returns) >= 25 and estimated_risk > 1e-8: gross = min(0.95, 0.12 / estimated_risk)",
    ],
  };
  const lines=[
    "# READABLE PSEUDOCODE, not an independently runnable script",
    `ASSETS = [${spec.symbols.map(s=>JSON.stringify(s)).join(", ")}]`,
    `REBALANCE_EVERY = ${spec.rebalance_sessions} common trading sessions`,
    `EXECUTION_DELAY = ${spec.delay_sessions} session(s)`,
    `MAX_ASSET_WEIGHT = ${spec.max_position_pct / 100}`,
    "",
    "on_rebalance:",
    "  # Use completed prices only. No future candles.",
    "  vol_60[asset] = max(stdev(last_60_daily_returns), 0.002)",
    ...((modelLines[spec.model]??["# Unsupported model"]).map(line=>"  "+line)),
    "  if sum(raw.values()) == 0: target = all_cash; stop",
    spec.model==="volatility_target"?"  # gross computed above":"  gross = 0.95",
    "  target[asset] = min(MAX_ASSET_WEIGHT, gross * raw[asset] / sum(raw))",
    "  enforce category caps (equity .70, bond .55, commodity .35, real_estate .20, crypto .10)",
    "  keep any excess allocation in cash; do not redistribute capped weight",
    "  at eligible common-session open, sell excess positions before buying deficits",
    "  # Real orders are NEVER submitted; paper/live actions require review.",
  ];
  return lines.join("\n");
}

export default function TournamentStrategyInspector({
  spec,exactCode,costs,context="research",
}:{
  spec:TournamentModelSpec;exactCode?:string;costs?:ResearchCosts;
  context?:"research"|"simulation"|"live";
}){
  const {t}=useI18n();
  const [copyStatus,setCopyStatus]=useState("");
  const code=useMemo(()=>{
    if(exactCode){
      try{
        const parsed:unknown=JSON.parse(exactCode);
        if(parsed&&typeof parsed==="object"&&!Array.isArray(parsed))
          return JSON.stringify(parsed,null,2);
      }catch{/* Fall back to the versioned parameters presented by the engine. */}
    }
    // A simulation session also stores changing counters. Show the actual
    // immutable model fields only, not those runtime fields, as configuration.
    const normalized:TournamentModelSpec={
      version:spec.version,model:spec.model,symbols:spec.symbols,
      max_position_pct:spec.max_position_pct,delay_sessions:spec.delay_sessions,
      rebalance_sessions:spec.rebalance_sessions,
      restricted_research:spec.restricted_research??false,
      short_proxy_research:spec.short_proxy_research??false,
    };
    return JSON.stringify(normalized,null,2);
  },[spec,exactCode]);
  const pseudocode=useMemo(()=>algorithmFor(spec),[spec]);
  const rules=modelRules[spec.model]??["No documented rules exist for this model."];
  const copy=(value:string)=>{
    if(!navigator.clipboard){setCopyStatus(t("Clipboard unavailable. Select and copy the code manually."));return;}
    void navigator.clipboard.writeText(value)
      .then(()=>setCopyStatus(t("Copied.")))
      .catch(()=>setCopyStatus(t("Clipboard unavailable. Select and copy the code manually.")));
  };
  return <section className="tsi" aria-label={t("Strategy logic and source")}>
    <header className="tsi-header">
      <div><h4>{t("Strategy logic and source")}</h4>
        <p>{t(modelDescription(spec.model))}</p></div>
      <a href={sourceLink} target="_blank" rel="noreferrer">{t("View actual Python allocation function")}</a>
    </header>
    <div className="tsi-fields">
      <div><small>{t("Research asset basket")}</small><strong>{spec.symbols.map(s=>s.toUpperCase()).join(" · ")}</strong></div>
      <div><small>{t("Single-asset cap")}</small><strong>{spec.max_position_pct}%</strong></div>
      <div><small>{t("Rebalance cadence")}</small><strong>{spec.rebalance_sessions} {t("common sessions")}</strong></div>
      <div><small>{t("Execution assumption")}</small><strong>{spec.delay_sessions} {t("session(s)")}</strong></div>
    </div>
    {(spec.restricted_research||spec.short_proxy_research)&&
      <p className="tsi-note">{t("This basket includes leveraged or inverse ETFs. The result is for research and simulation only, not approved live monitoring.")}</p>}
    <h5>{t("Exact allocation decision rules")}</h5>
    <ol className="tsi-rules">
      {rules.map((line,i)=><li key={i}>{t(line)}</li>)}
      <li>{t("Hold at most 95% in aggregate before asset and category caps; unused capital remains in cash.")}</li>
      <li>{t("Apply category exposure caps")}: {groupCaps.map(([name,cap])=>`${t(name)} ${cap}%`).join(", ")}.</li>
      <li>{t("Rebalance at the next eligible common-session open using completed historical data, selling before buying. No automatic brokerage execution.")}</li>
    </ol>
    {context==="simulation"&&<p className="tsi-note">{t("Historical replay uses the same target-weight function as tournament research, but its fill and fee approximation is different. Results may not match the tournament backtest exactly.")}</p>}
    {context==="live"&&<p className="tsi-note">{t("Live monitoring generates suggested order sizes from saved capital, current prices and confirmed fills. It does not read brokerage balances or place orders.")}</p>}
    {costs&&<p className="tsi-note">{t("Tournament research cost assumptions")}: {costs.slippage_bps??"?"} bps {t("slippage")}, {costs.commission_usd??"?"} USD {t("commission")}, {costs.fx_conversion_bps??"?"} bps {t("FX conversion")}, {costs.base_currency??"USD"} {t("base currency")}.</p>}
    <details className="tsi-code" open>
      <summary>{t("View full readable algorithm")}</summary>
      <div className="tsi-code-actions"><span>{t("Pseudocode, faithful to allocation logic, not executable Python")}</span>
        <button type="button" onClick={()=>copy(pseudocode)}>{t("Copy algorithm")}</button></div>
      <pre>{pseudocode}</pre>
    </details>
    <details className="tsi-code">
      <summary>{t("Exact machine-readable strategy configuration (JSON)")}</summary>
      <div className="tsi-code-actions"><span>{t("These are the actual model parameters, not a separate SMA script.")}</span>
        <button type="button" onClick={()=>copy(code)}>{t("Copy JSON")}</button></div>
      <pre>{code}</pre>
    </details>
    {copyStatus&&<p className="tsi-copy-status" role="status">{copyStatus}</p>}
  </section>;
}
