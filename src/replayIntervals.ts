import type { MarketBar } from "./api";

export type ReplayResolution = "1m" | "5m" | "15m" | "1h" | "1d";
export type ReplayWindow = "7D" | "30D" | "60D" | "6M" | "1Y" | "2Y" | "5Y" | "10Y" | "MAX";

export const REPLAY_WINDOWS: Record<ReplayResolution, readonly ReplayWindow[]> = {
  "1m": ["7D"],
  "5m": ["7D","30D","60D"],
  "15m": ["7D","30D","60D"],
  "1h": ["7D","30D","60D","6M","1Y"],
  "1d": ["1Y","2Y","5Y","10Y","MAX"],
};
const SECONDS: Record<ReplayResolution, number> = {
  "1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400,
};
export const RESOLUTIONS: ReplayResolution[] = ["1m","5m","15m","1h","1d"];
export const chartViewsFor = (base: ReplayResolution) =>
  RESOLUTIONS.filter(r=>SECONDS[r]>=SECONDS[base]);
export function groupTime(time: number, target: ReplayResolution) {
  const seconds = SECONDS[target];
  return Math.floor(time / seconds) * seconds;
}

/** Merge only observed bars. Missing historical candles are never interpolated.
 * OHLCV takes first open, observed max/min, last close and total volume.
 */
export function aggregateBars(bars: MarketBar[], target: ReplayResolution): MarketBar[] {
  const result: MarketBar[]=[];
  for(const bar of bars){
    const time=groupTime(bar.time,target);
    const last=result.at(-1);
    if(last&&last.time===time){
      last.high=Math.max(last.high,bar.high);
      last.low=Math.min(last.low,bar.low);
      last.close=bar.close;
      last.volume+=bar.volume;
    }else{
      result.push({...bar,time});
    }
  }
  return result;
}

export function chartTrades<T extends {time:number}>(fills:T[],target:ReplayResolution):T[]{
  return fills.map(fill=>({...fill,time:groupTime(fill.time,target)}));
}

export function showReplayTime(value:string|number,resolution:ReplayResolution) {
  const instant=typeof value==="number"?new Date(value*1000):
    value.length===10?new Date(value+"T00:00:00Z"):new Date(value);
  if(Number.isNaN(instant.valueOf()))return String(value);
  return resolution==="1d"
    ? instant.toLocaleDateString("en-CA",{year:"numeric",month:"short",day:"numeric",timeZone:"UTC"})
    : instant.toLocaleString("en-CA",{year:"numeric",month:"short",day:"numeric",
        hour:"2-digit",minute:"2-digit",hour12:false,timeZone:"America/Toronto"})+" ET";
}
