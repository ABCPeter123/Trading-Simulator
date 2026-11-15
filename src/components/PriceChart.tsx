import { useEffect, useRef } from "react";
import {
  CandlestickSeries, ColorType, createChart, CrosshairMode, HistogramSeries, LineSeries,
} from "lightweight-charts";
import type { UTCTimestamp } from "lightweight-charts";
import type { Asset, ChartStyle, TimeRange } from "../types";
import type { MarketBar } from "../api";

interface PriceChartProps {
  asset: Asset;
  range: TimeRange;
  style: ChartStyle;
  bars: MarketBar[];
}

export function PriceChart({ asset, range, style, bars }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const updateRef = useRef<((bars: MarketBar[]) => void) | null>(null);

  // Create the chart only when its symbol/style configuration changes.
  // Historical replay appends bars much more frequently, so it uses setData
  // below instead of tearing down the entire canvas every game tick.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#111923" },
        textColor: "#8696a9",
        fontFamily: "ui-sans-serif, system-ui, sans-serif",
        fontSize: 11,
        attributionLogo: true,
      },
      grid: { vertLines: { color: "#1c2733" }, horzLines: { color: "#1c2733" } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#25323f", scaleMargins: { top: 0.11, bottom: 0.23 } },
      timeScale: {
        borderColor: "#25323f", timeVisible: true, secondsVisible: false,
        rightOffset: 4, barSpacing: range === "1D" ? 7 : 5,
      },
      localization: { priceFormatter: (value: number) => value.toFixed(asset.decimals) },
    });
    const priceFormat = {
      type: "price" as const,
      precision: asset.decimals,
      minMove: 1 / 10 ** asset.decimals,
    };
    let updatePrice: (newBars: MarketBar[]) => void;
    if (style === "candles") {
      const series = chart.addSeries(CandlestickSeries, {
        upColor: "#35ca98", downColor: "#f96873", borderVisible: false,
        wickUpColor: "#35ca98", wickDownColor: "#f96873", priceFormat,
      });
      updatePrice = (newBars) => series.setData(newBars.map(bar => ({
        time: bar.time as UTCTimestamp,
        open: bar.open, high: bar.high, low: bar.low, close: bar.close,
      })));
    } else {
      const series = chart.addSeries(LineSeries, {
        color: "#53a9ee", lineWidth: 2, priceFormat,
      });
      updatePrice = (newBars) => series.setData(newBars.map(bar => ({
        time: bar.time as UTCTimestamp, value: bar.close,
      })));
    }
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: {type:"volume"},
      priceScaleId:"",
      lastValueVisible:false,
      priceLineVisible:false,
    });
    volume.priceScale().applyOptions({scaleMargins: {top:0.78, bottom:0.01}});
    updateRef.current = (newBars) => {
      if (!newBars.length) return;
      updatePrice(newBars);
      volume.setData(newBars.map(bar => ({
        time:bar.time as UTCTimestamp,
        value:bar.volume,
        color:bar.close>=bar.open ? "rgba(53,202,152,.28)" : "rgba(249,104,111,.27)",
      })));
      chart.timeScale().fitContent();
    };
    return () => {
      updateRef.current = null;
      chart.remove();
    };
  }, [asset, range, style]);

  useEffect(() => {
    updateRef.current?.(bars);
  }, [bars, asset, range, style]);

  return <div className="chart-canvas" ref={containerRef} aria-label={`${asset.symbol} historical market price chart`}/>;
}
