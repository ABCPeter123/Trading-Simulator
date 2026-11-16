import { useEffect, useMemo, useRef, useState } from "react";
import {
  AreaSeries, ColorType, createChart, CrosshairMode, LineSeries,
} from "lightweight-charts";
import type { UTCTimestamp } from "lightweight-charts";
import { Activity, BarChart3, Download, Layers, RefreshCcw, TrendingDown, TrendingUp, Wallet } from "lucide-react";
import { formatMoney } from "./data/demoMarket";
import { getStrategyReport } from "./strategyAnalyticsApi";
import type { StrategyReport, AnalyticsPoint } from "./strategyAnalyticsApi";
import { useI18n } from "./i18n";
import "./analytics.css";

type Window = "ALL" | "5" | "20" | "60" | "126" | "252" | "CUSTOM";
const WINDOWS:Window[]=["ALL","5","20","60","126","252"];
const shortNum=(n:number)=>n.toLocaleString("en-US",{maximumFractionDigits:2});
const pct=(n:number|null)=>n===null?"N/A":`${n>=0?"+":""}${n.toFixed(2)}%`;
const epoch=(s:string)=>(Date.parse(s+"T00:00:00Z")/1000) as UTCTimestamp;

interface PlotLine {
  name:string;
  color:string;
  points:{time:UTCTimestamp;value:number}[];
}
function LinePlot({data,format="money",area=false}:{
  data:PlotLine[];
  format?:"money"|"percent";
  area?:boolean;
}) {
  const node=useRef<HTMLDivElement>(null);
  const key=data.map(line=>line.name+"|"+line.color).join(",");
  const updateRef=useRef<((lines:PlotLine[])=>void)|null>(null);
  useEffect(()=>{
    const element=node.current;
    if(!element)return;
    const chart=createChart(element,{
      autoSize:true,
      layout:{background:{type:ColorType.Solid,color:"#111c29"},textColor:"#879aaf",fontSize:10},
      grid:{vertLines:{color:"#1e3040"},horzLines:{color:"#1e3040"}},
      crosshair:{mode:CrosshairMode.Normal},
      rightPriceScale:{borderColor:"#293c4c",scaleMargins:{top:.1,bottom:.1}},
      timeScale:{borderColor:"#293c4c",timeVisible:false,rightOffset:3},
      localization:{
        priceFormatter:(value:number)=>format==="percent"?value.toFixed(2)+"%":formatMoney(value),
      },
    });
    const plots=data.map((line,i)=>{
      const s=area&&i===0?chart.addSeries(AreaSeries,{
        lineColor:line.color,topColor:line.color+"44",bottomColor:line.color+"00",
        lineWidth:2,priceLineVisible:false,
      }):chart.addSeries(LineSeries,{
        color:line.color,lineWidth:2,priceLineVisible:false,
      });
      return s;
    });
    updateRef.current=(lines)=>{
      lines.forEach((line,i)=>plots[i].setData(line.points));
      chart.timeScale().fitContent();
    };
    return ()=>{updateRef.current=null;chart.remove();};
  },[key,area,format]);
  useEffect(()=>{updateRef.current?.(data);},[data,key,area,format]);
  return <div className="an-chart-canvas" ref={node}/>;
}

function csv(data:StrategyReport) {
  const header=["day","equity_usd","equal_weight_buy_hold_usd","cash_usd","invested_usd","strategy_return_pct","benchmark_return_pct","drawdown_pct","total_fees_usd"];
  const rows=data.curve.map(p=>[p.day,p.equity,p.benchmark,p.cash,p.invested,p.return_pct,p.benchmark_pct,p.drawdown_pct,p.fee_total].join(","));
  const blob=new Blob([header.join(",")+"\n"+rows.join("\n")+"\n"],{type:"text/csv;charset=utf-8"});
  const url=URL.createObjectURL(blob);
  const link=document.createElement("a");link.href=url;
  link.download=`strategy-analytics-${data.end_day}.csv`;link.click();
  URL.revokeObjectURL(url);
}
function tradesCsv(data:StrategyReport) {
  const header=["day","symbol_id","side","quantity","fill_price","notional_usd","fee_usd","cash_delta_usd","origin"];
  const rows=data.executions.map(fill=>[
    fill.day,fill.asset_id,fill.side,fill.quantity,fill.price,
    fill.notional,fill.fee,fill.cash_change,fill.source,
  ].join(","));
  const blob=new Blob([header.join(",")+"\n"+rows.join("\n")+"\n"],{type:"text/csv;charset=utf-8"});
  const url=URL.createObjectURL(blob);
  const anchor=document.createElement("a");anchor.href=url;
  anchor.download=`strategy-executions-${data.end_day}.csv`;anchor.click();
  URL.revokeObjectURL(url);
}
function Metric({name,value,note}: {name:string;value:string;note?:string}) {
  return <div className="an-metric"><small>{name}</small><strong>{value}</strong>{note&&<span>{note}</span>}</div>;
}
const toSeries=(data:AnalyticsPoint[],key:keyof AnalyticsPoint)=>data.map(p=>({
  time:epoch(p.day),value:Number(p[key]),
}));

export default function StrategyAnalytics({runId,step,mode,assetName,onReport}:{
  runId:string;step:number;mode:"portfolio"|"single";assetName:(id:string)=>string;
  onReport?:(report:StrategyReport)=>void;
}) {
  const {t}=useI18n();
  const [report,setReport]=useState<StrategyReport|null>(null);
  const [error,setError]=useState("");
  const [loading,setLoading]=useState(false);
  const [window,setWindow]=useState<Window>("ALL");
  const [fromDay,setFromDay]=useState("");
  const [toDay,setToDay]=useState("");
  useEffect(()=>{
    let cancelled=false;
    setLoading(true);
    void getStrategyReport(mode,runId).then(value=>{
      if(!cancelled){setReport(value);onReport?.(value);setError("");}
    }).catch(e=>{
      if(!cancelled)setError(e instanceof Error?e.message:"Analytics unavailable.");
    }).finally(()=>{if(!cancelled)setLoading(false);});
    return ()=>{cancelled=true;};
  },[mode,runId,step]);
  const data=useMemo(()=>{
    if(!report)return [];
    if (window==="ALL") return report.curve;
    if (window==="CUSTOM") return report.curve.filter(p=>(!fromDay||p.day>=fromDay)&&(!toDay||p.day<=toDay));
    return report.curve.slice(-(Number(window)+1));
  },[report,window,fromDay,toDay]);
  const plots=useMemo(()=>({
    equity:[
      {name:t("Strategy equity"),color:"#55d0a6",points:toSeries(data,"equity")},
      {name:t("Equal-weight benchmark"),color:"#b7a4fe",points:toSeries(data,"benchmark")},
    ],
    drawdown:[{name:t("Drawdown"),color:"#f2828e",points:toSeries(data,"drawdown_pct")}],
    capital:[
      {name:t("Capital invested"),color:"#e8b47d",points:toSeries(data,"invested")},
      {name:t("Cash balance"),color:"#6db6e7",points:toSeries(data,"cash")},
    ],
  }),[data,t]);
  const windowResult=useMemo(()=>{
    if(data.length===0)return null;
    const first=data[0],last=data.at(-1)!;
    return {
      own:((last.equity/first.equity)-1)*100,
      benchmark:((last.benchmark/first.benchmark)-1)*100,
    };
  },[data]);

  return <section className="an-dashboard" aria-label={t("Strategy analytics")}>
    <div className="an-heading">
      <div><span className="arc-upper">{t("PERFORMANCE RESEARCH")}</span>
        <h2><BarChart3 size={20}/>{t("Strategy analytics")}</h2>
        <p>{t("Analyze performance, risk, capital deployed and individual executions using only revealed historical data.")}</p>
      </div>
      <div className="an-actions">
        {loading&&<span className="an-loading"><RefreshCcw size={14}/>{t("Updating")}</span>}
        {report&&<><button onClick={()=>csv(report)}><Download size={15}/>{t("Export CSV")}</button><button onClick={()=>tradesCsv(report)}><Download size={15}/>{t("Export trades")}</button></>}
      </div>
    </div>
    {error&&<div className="arc-error" role="alert">{t(error)}</div>}
    {report&&<>
      <div className="an-period-row">
        <span>{t("Show last")}</span>
        {WINDOWS.map(k=><button key={k} className={k===window?"active":""}
          onClick={()=>setWindow(k)}>{k==="ALL"?t("All"):k+" "+t("steps")}</button>)}
        <button className={window==="CUSTOM"?"active":""} onClick={()=>setWindow("CUSTOM")}>{t("Custom dates")}</button>
        {window==="CUSTOM"&&<><label className="an-date-label">{t("From")}<input type="date" min={report.start_day} max={report.end_day}
          value={fromDay} onChange={e=>setFromDay(e.target.value)}/></label>
          <label className="an-date-label">{t("To")}<input type="date" min={report.start_day} max={report.end_day}
            value={toDay} onChange={e=>setToDay(e.target.value)}/></label></>}
        <span className="an-range">{data[0]?.day??t("No data")} / {data.at(-1)?.day??t("No data")}</span>
      </div>
      <div className="an-metrics">
        <Metric name={t("Strategy return")} value={pct(windowResult?.own??null)}
          note={t("Selected period")}/>
        <Metric name={t("Benchmark return")} value={pct(windowResult?.benchmark??null)}
          note={t("Equal-weight price-only")}/>
        <Metric name={t("Excess return")} value={pct(windowResult?windowResult.own-windowResult.benchmark:null)}/>
        <Metric name={t("Maximum drawdown")} value={pct(report.summary.max_drawdown_pct)} note={t("Full season to date")}/>
        <Metric name={t("Capital invested")} value={formatMoney(report.summary.current_invested)}
          note={`${shortNum(report.summary.current_invested/Math.max(report.summary.current_equity,1)*100)}% ${t("of equity")}`}/>
        <Metric name={t("Trading costs")} value={formatMoney(report.summary.total_fees)}
          note={`${report.summary.fill_count} ${t("fills")}`}/>
        <Metric name={t("Trade turnover")} value={formatMoney(report.summary.total_notional_traded)}/>
        <Metric name={t("Profitable exits")} value={pct(report.summary.profitable_exit_rate_pct)}
          note={`${report.summary.winning_exits} ${t("positive")} / ${report.summary.losing_exits} ${t("non-positive")}`}/>
      </div>
      <div className="an-charts">
        <div className="an-plot">
          <header><TrendingUp size={16}/><strong>{t("Equity vs benchmark")}</strong></header>
          <div className="an-legend"><span style={{color:"#55d0a6"}}>{t("Strategy equity")}</span><span style={{color:"#b7a4fe"}}>{t("Equal-weight benchmark")}</span></div>
          <LinePlot data={plots.equity}/>
        </div>
        <div className="an-plot">
          <header><TrendingDown size={16}/><strong>{t("Drawdown history")}</strong></header>
          <div className="an-legend"><span style={{color:"#f2828e"}}>{t("Peak-to-trough decline")}</span></div>
          <LinePlot data={plots.drawdown} area format="percent"/>
        </div>
        <div className="an-plot">
          <header><Wallet size={16}/><strong>{t("Cash vs invested capital")}</strong></header>
          <div className="an-legend"><span style={{color:"#e8b47d"}}>{t("Capital invested")}</span><span style={{color:"#6db6e7"}}>{t("Cash balance")}</span></div>
          <LinePlot data={plots.capital}/>
        </div>
      </div>
      <div className="an-detail-grid">
        <section>
          <header><Activity size={16}/><strong>{t("Rolling-period performance")}</strong></header>
          <div className="arc-table-scroll"><table>
            <thead><tr><th>{t("Period")}</th><th>{t("Strategy")}</th><th>{t("Benchmark")}</th><th>{t("Excess")}</th></tr></thead>
            <tbody>{[5,20,60,126,252].map(n=>{
              const a=report.rolling[String(n)];
              return <tr key={n}><td>{n} {t("steps")}</td>
                <td>{a?pct(a.return_pct):"N/A"}</td>
                <td>{a?pct(a.benchmark_pct):"N/A"}</td>
                <td>{a?pct(a.return_pct-a.benchmark_pct):"N/A"}</td>
              </tr>;
            })}</tbody>
          </table></div>
        </section>
        <section>
          <header><Layers size={16}/><strong>{t("Position attribution")}</strong></header>
          <div className="arc-table-scroll"><table>
            <thead><tr><th>{t("Asset")}</th><th>{t("Invested")}</th><th>{t("Weight")}</th><th>{t("Price return")}</th><th>{t("Unrealized P&L")}</th><th>{t("Realized P&L")}</th></tr></thead>
            <tbody>{report.allocations.map(a=><tr key={a.asset_id}>
              <td>{assetName(a.asset_id)}</td><td>{formatMoney(a.invested)}</td>
              <td>{a.weight_pct.toFixed(1)}%</td>
              <td>{pct(a.price_return_pct)}</td>
              <td>{formatMoney(a.unrealized_pnl)}</td>
              <td>{formatMoney(a.realized_pnl)}</td>
            </tr>)}</tbody>
          </table></div>
        </section>
      </div>
      <section className="an-executions">
        <header><Activity size={16}/><strong>{t("Execution audit")}</strong><span>{report.executions.length} {t("fills")}</span></header>
        <div className="arc-table-scroll"><table>
          <thead><tr><th>{t("DATE")}</th><th>{t("SYMBOL")}</th><th>{t("SIDE")}</th><th>{t("QTY")}</th><th>{t("PRICE")}</th><th>{t("Notional USD")}</th><th>{t("FEE")}</th><th>{t("Cash change")}</th><th>{t("ENGINE")}</th></tr></thead>
          <tbody>{report.executions.length===0
            ? <tr><td colSpan={9}>{t("No fills yet. Place a trade, then advance the timeline.")}</td></tr>
            : report.executions.slice().reverse().map((fill,i)=><tr key={fill.day+"-"+fill.asset_id+"-"+i}>
              <td>{fill.day}</td><td>{assetName(fill.asset_id)}</td>
              <td className={fill.side==="buy"?"positive":"negative"}>{t(fill.side.toUpperCase())}</td>
              <td>{shortNum(fill.quantity)}</td><td>{formatMoney(fill.price)}</td>
              <td>{formatMoney(fill.notional)}</td><td>{formatMoney(fill.fee)}</td>
              <td>{formatMoney(fill.cash_change)}</td><td>{t(fill.source)}</td>
            </tr>)}</tbody>
        </table></div>
      </section>
      <p className="an-method"><strong>{t("Methodology")}:</strong> {t(report.methodology)}</p>
    </>}
  </section>;
}
