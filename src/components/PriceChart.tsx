import { useEffect, useMemo, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
} from "lightweight-charts";
import type { Asset, ChartStyle, TimeRange } from "../types";
import { createDemoSeries } from "../data/demoMarket";

interface PriceChartProps {
  asset: Asset;
  range: TimeRange;
  style: ChartStyle;
}

export function PriceChart({ asset, range, style }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const series = useMemo(() => createDemoSeries(asset, range), [asset, range]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#111923" },
        textColor: "#8696a9",
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
        fontSize: 11,
        attributionLogo: true,
      },
      grid: {
        vertLines: { color: "#1c2733" },
        horzLines: { color: "#1c2733" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: {
        borderColor: "#25323f",
        scaleMargins: { top: 0.11, bottom: 0.23 },
      },
      timeScale: {
        borderColor: "#25323f",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 4,
        barSpacing: range === "1D" ? 7 : 5,
      },
      localization: {
        priceFormatter: (value: number) => value.toFixed(asset.decimals),
      },
    });

    const format = {
      type: "price" as const,
      precision: asset.decimals,
      minMove: 1 / 10 ** asset.decimals,
    };

    if (style === "candles") {
      const candles = chart.addSeries(CandlestickSeries, {
        upColor: "#35ca98",
        downColor: "#f96873",
        borderVisible: false,
        wickUpColor: "#35ca98",
        wickDownColor: "#f96873",
        priceLineColor: "#35ca98",
        priceFormat: format,
      });
      candles.setData(series.candles);
    } else {
      const line = chart.addSeries(LineSeries, {
        color: "#53a9ee",
        lineWidth: 2,
        crosshairMarkerRadius: 4,
        priceFormat: format,
      });
      line.setData(series.candles.map(({ time, close }) => ({ time, value: close })));
    }

    const volume = chart.addSeries(HistogramSeries, {
      color: "rgba(53,202,152,.28)",
      priceFormat: { type: "volume" },
      priceScaleId: "",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    volume.priceScale().applyOptions({
      scaleMargins: { top: 0.78, bottom: 0.01 },
    });
    volume.setData(series.volumes);
    chart.timeScale().fitContent();

    return () => chart.remove();
  }, [asset, range, series, style]);

  return <div className="chart-canvas" ref={containerRef} aria-label={`Synthetic ${asset.symbol} ${range} price chart`} />;
}
