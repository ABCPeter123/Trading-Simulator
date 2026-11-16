import { useEffect, useMemo, useRef } from "react";
import {
  CandlestickSeries, ColorType, createChart, createSeriesMarkers,
  CrosshairMode, HistogramSeries, LineSeries,
} from "lightweight-charts";
import type { SeriesMarker, UTCTimestamp } from "lightweight-charts";
import type { Asset, ChartStyle, TimeRange } from "../types";
import type { MarketBar } from "../api";

export interface ChartTrade {
  time: number;
  side: "buy" | "sell";
  quantity: number;
  price: number;
  source?: string;
}
interface PriceChartProps {
  asset: Asset;
  range: TimeRange;
  style: ChartStyle;
  bars: MarketBar[];
  visibleWindow?: number;
  smaPeriods?: number[];
  trades?: ChartTrade[];
  showCrossovers?: boolean;
}

/** Rolling, backward-looking SMA. Each plotted value uses bars through that close only. */
export function smaOverlay(bars: MarketBar[], period: number) {
  if (!Number.isInteger(period) || period < 2 || period > 200) return [];
  let sum = 0;
  const output: {time: UTCTimestamp; value: number}[] = [];
  for (let i=0;i<bars.length;i++) {
    sum += bars[i].close;
    if (i >= period) sum -= bars[i-period].close;
    if (i >= period-1) output.push({time: bars[i].time as UTCTimestamp, value: sum/period});
  }
  return output;
}

export function PriceChart({
  asset, range, style, bars, visibleWindow, smaPeriods = [], trades = [], showCrossovers = false,
}: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const updateRef = useRef<((bars: MarketBar[], fills: ChartTrade[]) => void) | null>(null);
  const key = smaPeriods.join(",");
  const validPeriods = useMemo(
    () => [...new Set(smaPeriods)].filter(n=>Number.isInteger(n)&&n>=2&&n<=200),
    [key],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#111923" },
        textColor: "#8696a9", fontFamily: "ui-sans-serif, system-ui, sans-serif",
        fontSize: 11, attributionLogo: true,
      },
      grid: {vertLines:{color:"#1c2733"},horzLines:{color:"#1c2733"}},
      crosshair: {mode:CrosshairMode.Normal},
      rightPriceScale:{borderColor:"#25323f",scaleMargins:{top:.11,bottom:.23}},
      timeScale:{
        borderColor:"#25323f",timeVisible:true,secondsVisible:false,
        rightOffset:4,barSpacing:range==="1D"?7:5,
      },
      localization:{priceFormatter:(value:number)=>value.toFixed(asset.decimals)},
    });
    const priceFormat = {
      type:"price" as const,
      precision:asset.decimals,
      minMove:1 / 10 ** asset.decimals,
    };
    let updatePrice: (bars:MarketBar[])=>void;
    let updateMarkers: (markers:SeriesMarker<UTCTimestamp>[])=>void;

    if (style==="candles") {
      const series = chart.addSeries(CandlestickSeries, {
        upColor:"#35ca98",downColor:"#f96873",borderVisible:false,
        wickUpColor:"#35ca98",wickDownColor:"#f96873",priceFormat,
      });
      const plugin = createSeriesMarkers(series, []);
      updatePrice = data=>series.setData(data.map(b=>({
        time:b.time as UTCTimestamp,open:b.open,high:b.high,low:b.low,close:b.close,
      })));
      updateMarkers = markers=>plugin.setMarkers(markers);
    } else {
      const series = chart.addSeries(LineSeries,{
        color:"#53a9ee",lineWidth:2,priceFormat,
      });
      const plugin=createSeriesMarkers(series,[]);
      updatePrice=data=>series.setData(data.map(b=>({
        time:b.time as UTCTimestamp,value:b.close,
      })));
      updateMarkers=markers=>plugin.setMarkers(markers);
    }

    const maColors=["#e9bb74","#a99dff","#61d6e5","#e983c9"];
    const moving = validPeriods.map((period,i)=>({
      period, series:chart.addSeries(LineSeries,{
        title:`SMA ${period}`, color:maColors[i%maColors.length],
        lineWidth:2,priceLineVisible:false,lastValueVisible:true,priceFormat,
      }),
    }));
    const volume=chart.addSeries(HistogramSeries,{
      priceFormat:{type:"volume"},priceScaleId:"",
      lastValueVisible:false,priceLineVisible:false,
    });
    volume.priceScale().applyOptions({scaleMargins:{top:.78,bottom:.01}});

    updateRef.current=(data,fills)=>{
      updatePrice(data);
      volume.setData(data.map(bar=>({
        time:bar.time as UTCTimestamp,value:bar.volume,
        color:bar.close>=bar.open?"rgba(53,202,152,.28)":"rgba(249,104,111,.27)",
      })));
      for (const {period,series} of moving) series.setData(smaOverlay(data,period));
      const available=new Set(data.map(b=>b.time));
      const markers:SeriesMarker<UTCTimestamp>[]=[];
      if (showCrossovers && validPeriods.length>=2) {
        const [fast,slow] = validPeriods;
        const f=smaOverlay(data,fast),sl=smaOverlay(data,slow);
        const fm=new Map(f.map(p=>[p.time,p.value]));
        const sm=new Map(sl.map(p=>[p.time,p.value]));
        let previous:number|null=null;
        for(const candle of data){
          const time=candle.time as UTCTimestamp;
          const a=fm.get(time),b=sm.get(time);
          if(a===undefined||b===undefined){previous=null;continue;}
          const difference=a-b;
          if(previous!==null && previous<=0 && difference>0){
            markers.push({time,position:"belowBar",color:"#d7b674",shape:"circle",text:"SMA ↑"});
          }else if(previous!==null&&previous>=0&&difference<0){
            markers.push({time,position:"aboveBar",color:"#d7b674",shape:"circle",text:"SMA ↓"});
          }
          previous=difference;
        }
      }
      for(const fill of fills.slice(-250)){
        if(!available.has(fill.time))continue;
        markers.push({
          time:fill.time as UTCTimestamp,
          position:fill.side==="buy"?"belowBar":"aboveBar",
          color:fill.side==="buy"?"#4ad4a0":"#fa7c8a",
          shape:fill.side==="buy"?"arrowUp":"arrowDown",
          text:`${fill.side==="buy"?"B":"S"} ${Number(fill.quantity).toLocaleString("en-US",{maximumFractionDigits:3})}`,
        });
      }
      markers.sort((a,b)=>(a.time as number)-(b.time as number));
      updateMarkers(markers);
      if (visibleWindow && data.length>visibleWindow) {
        chart.timeScale().setVisibleLogicalRange({
          from:data.length-visibleWindow,to:data.length+3,
        });
      } else {
        chart.timeScale().fitContent();
      }
    };
    return ()=>{updateRef.current=null;chart.remove();};
  },[asset,range,style,visibleWindow,key,showCrossovers]);

  useEffect(()=>{
    updateRef.current?.(bars,trades);
  },[bars,trades,asset,range,style,visibleWindow,key,showCrossovers]);

  return <div className="chart-canvas" ref={containerRef}
    aria-label={`${asset.symbol} price chart with historical fills and indicators`}/>;
}
