import { useEffect, useMemo, useRef, useState } from "react";
import { LineSeries, ColorType, createChart } from "lightweight-charts";
import type { UTCTimestamp } from "lightweight-charts";
import { Activity, TrendingUp, RefreshCcw, Calculator } from "lucide-react";
import { useI18n } from "./i18n";
import { getScenarios, priceEuropeanOption } from "./stochasticApi";
import type { ScenarioResult,OptionPrices } from "./stochasticApi";
import "./stochastic.css";
import { useChartDimensions } from "./components/useChartDimensions";

const money=(x:number)=>Number.isFinite(x)?x.toLocaleString("en-US",{minimumFractionDigits:2,maximumFractionDigits:2}):"N/A";
function FanChart({result}:{result:ScenarioResult}) {
  const {ref:el,width,height,visible}=useChartDimensions();
  const resizeRef=useRef<((width:number,height:number)=>void)|null>(null);
  useEffect(()=>{
    const element=el.current;
    if(!element||!visible)return;
    const chart=createChart(element,{
      autoSize:false,width,height,layout:{background:{type:ColorType.Solid,color:"#101d2c"},textColor:"#a0aec0"},
      grid:{vertLines:{color:"#233346"},horzLines:{color:"#233346"}},
      rightPriceScale:{borderColor:"#37465b"},
      timeScale:{borderColor:"#37465b",visible:false},
      localization:{priceFormatter:(n:number)=>money(n)},
    });
    resizeRef.current=(nextWidth,nextHeight)=>chart.resize(nextWidth,nextHeight);
    // Every simulated trajectory is loaded, not an arbitrary 1-in-16 sample.
    // Thin transparent traces keep the full modeled distribution readable.
    for(const trajectory of result.paths){
      const series=chart.addSeries(LineSeries,{
        color:"rgba(107,144,190,.055)",lineWidth:1,lastValueVisible:false,
        priceLineVisible:false,crosshairMarkerVisible:false,
      });
      series.setData(trajectory.map((value,step)=>({time:(step+1) as UTCTimestamp,value})));
    }
    // Draw the quantiles last so their boundaries remain legible.
    const colors=["#67569b","#8086ca","#eecc79","#7fb1ce","#67569b"];
    for(const [i,key] of (["p05","p25","median","p75","p95"] as const).entries()){
      const series=chart.addSeries(LineSeries,{
        color:colors[i],lineWidth:key==="median"?3:1,
        priceLineVisible:false,lastValueVisible:key==="median",
        title:key.toUpperCase(),crosshairMarkerVisible:key==="median",
      });
      series.setData(result.quantiles.map(point=>({time:(point.step+1) as UTCTimestamp,value:point[key]})));
    }
    element.dataset.loadedPaths=String(result.paths.length);
    element.dataset.loadedSteps=String(result.quantiles.length);
    chart.timeScale().fitContent();
    return ()=>{resizeRef.current=null;chart.remove();};
  },[result,visible]);
  useEffect(()=>{if(visible)resizeRef.current?.(width,height);},[visible,width,height]);
  return <div className="forecast-plot" ref={el}/>;
}
export default function StochasticResearch({mode,runId,assetIds,step,viewingPast,onStrategy}:{
  mode:"single"|"portfolio";runId:string;assetIds:string[];step:number;
  viewingPast?:boolean;onStrategy:(code:string)=>void;
}) {
  const {t}=useI18n();
  const [symbol,setSymbol]=useState(assetIds[0]??"");
  const [lookback,setLookback]=useState(60);
  const [horizon,setHorizon]=useState(20);
  const [report,setReport]=useState<ScenarioResult|null>(null);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState("");
  const [strike,setStrike]=useState("");
  const [maturity,setMaturity]=useState(.25);
  const [rate,setRate]=useState(.03);
  const [volatility,setVolatility]=useState(.2);
  const [prices,setPrices]=useState<OptionPrices|null>(null);
  useEffect(()=>{setSymbol(assetIds[0]??"");setReport(null);},[runId]);
  useEffect(()=>{setReport(null);},[step,symbol,lookback,horizon,viewingPast]);
  async function calculate() {
    if(viewingPast)return;
    setLoading(true);setError("");
    try {
      const value=await getScenarios(mode,runId,symbol,horizon,lookback);
      setReport(value);
      setStrike(String(value.spot.toFixed(2)));
      setPrices(null);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setLoading(false);}
  }
  const signal=useMemo(()=>mode==="portfolio"
    ? `WHEN ${symbol} PROB_UP(${horizon}) CROSSES ABOVE 60 BUY 25% ${symbol}\nWHEN ${symbol} PROB_UP(${horizon}) CROSSES BELOW 40 SELL 100% ${symbol}`
    : `WHEN PROB_UP(${horizon}) CROSSES ABOVE 60 BUY 25%\nWHEN PROB_UP(${horizon}) CROSSES BELOW 40 SELL 100%`,[mode,symbol,horizon]);
  return <section className="forecast-panel">
    <header><Activity size={18}/><div><h2>{t("Stochastic Scenario Research")}</h2>
      <p>{t("256 hypothetical GBM paths fitted only to revealed historical candles. Not price predictions.")}</p></div></header>
    {viewingPast&&<p className="forecast-note">{t("Return to the latest replay step before running a new scenario.")}</p>}
    <div className="forecast-controls">
      <label>{t("Instrument")}<select value={symbol} onChange={e=>setSymbol(e.target.value)}>
        {assetIds.map(id=><option key={id} value={id}>{id.toUpperCase()}</option>)}
      </select></label>
      <label>{t("Historical lookback (candles)")}<select value={lookback} onChange={e=>setLookback(Number(e.target.value))}>
        {[20,40,60,100,150,252].map(n=><option key={n} value={n}>{n}</option>)}
      </select></label>
      <label>{t("Future horizon (candles)")}<select value={horizon} onChange={e=>setHorizon(Number(e.target.value))}>
        {[5,10,20,30,40,60].map(n=><option key={n} value={n}>{n}</option>)}
      </select></label>
      <button disabled={loading||viewingPast} onClick={()=>void calculate()}><RefreshCcw size={15}/>{loading?t("Calculating..."):t("Run 256 scenarios")}</button>
    </div>
    {error&&<p className="forecast-error" role="alert">{error}</p>}
    {report&&<>
      <div className="forecast-metrics">
        <div><small>{t("Current observed price")}</small><strong>{money(report.spot)}</strong></div>
        <div><small>{t("Model probability of rise")}</small><strong>{report.prob_up_model_pct.toFixed(1)}%</strong></div>
        <div><small>{t("Median scenario endpoint")}</small><strong>{money(report.median_terminal)}</strong></div>
        <div><small>{t("5%-95% modeled range")}</small><strong>{money(report.quantiles.at(-1)!.p05)} to {money(report.quantiles.at(-1)!.p95)}</strong></div>
      </div>
      <div className="forecast-legend">
        <span>{t("All 256 modeled paths shown; percentile curves reflect the full distribution.")}</span>
        <b>{t("Purple: tail percentiles")}</b><b>{t("Yellow: median")}</b>
      </div>
      <FanChart result={report}/>
      <p className="forecast-note">{t("A scenario range is conditional on fitted historical drift and volatility. It is not a forecast confidence guarantee.")}</p>
      <div className="forecast-dsl">
        <h3><TrendingUp size={15}/>{t("Forecast-aware strategy example")}</h3>
        <p>{t("PROB_UP(h) measures a historical-model probability from revealed closes, not future market data.")}</p>
        <pre>{signal}</pre>
        <button type="button" onClick={()=>onStrategy(signal)}>{t("Insert proposal into strategy editor")}</button>
      </div>
      <div className="forecast-option">
        <h3><Calculator size={15}/>{t("Black-Scholes option valuation")}</h3>
        <p>{t("Black-Scholes prices theoretical European options under risk-neutral assumptions. It does not predict the asset price.")}</p>
        <div className="forecast-controls">
          <label>{t("Strike")}<input type="number" min=".01" step="any" value={strike} onChange={e=>setStrike(e.target.value)}/></label>
          <label>{t("Years to expiry")}<input type="number" min=".001" step=".01" value={maturity} onChange={e=>setMaturity(Number(e.target.value))}/></label>
          <label>{t("Annual volatility (manual assumption)")}<input type="number" min="0" step=".01" value={volatility} onChange={e=>setVolatility(Number(e.target.value))}/></label>
          <label>{t("Risk-free rate")}<input type="number" step=".01" value={rate} onChange={e=>setRate(Number(e.target.value))}/></label>
          <button onClick={()=>void priceEuropeanOption({spot:report.spot,strike:Number(strike),maturity_years:maturity,volatility_annual:volatility,risk_free_rate:rate}).then(setPrices).catch(e=>setError(String(e)))}>{t("Price option")}</button>
        </div>
        {prices&&<p className="forecast-valuation">{t("Call value")}: {money(prices.call)} | {t("Put value")}: {money(prices.put)}</p>}
      </div>
    </>}
  </section>;
}
