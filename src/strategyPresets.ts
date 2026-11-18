/** Deterministic safe DSL presets. Nothing auto-executes or deploys.
 * These are starting hypotheses, not historical winners or broker orders.
 */
export interface StrategyPreset {id:string;title:string;description:string;code:string}
const sma=(fast:number,slow:number,pct:number)=>[
  "WHEN SMA("+fast+") CROSSES ABOVE SMA("+slow+") BUY "+pct+"%",
  "WHEN SMA("+fast+") CROSSES BELOW SMA("+slow+") SELL 100%",
].join("\n");
export const SINGLE_PRESETS:StrategyPreset[]=[
  {id:"balanced-trend",title:"Balanced SMA trend",description:"20/50-day trend with 25% available-cash sizing.",code:sma(20,50,25)},
  {id:"slow-trend",title:"Slow trend",description:"50/100-day signals, 20% cash sizing.",code:sma(50,100,20)},
  {id:"fast-trend",title:"Fast momentum",description:"10/30-day crossover, trades more often.",code:sma(10,30,20)},
  {id:"swing-trend",title:"Swing trend",description:"15/60-day crossover.",code:sma(15,60,30)},
  {id:"rsi-rebound",title:"RSI rebound",description:"Buy oversold rebounds, exit on overbought edge.",code:"WHEN RSI(14) BELOW 30 BUY 20%\nWHEN RSI(14) ABOVE 70 SELL 100%"},
  {id:"rsi-defensive",title:"Conservative RSI",description:"Tighter position sizing with RSI signals.",code:"WHEN RSI(14) BELOW 25 BUY 10%\nWHEN RSI(14) ABOVE 65 SELL 100%"},
  {id:"price-regime",title:"Price regime",description:"Trade price crossings of the 50-day trend.",code:"WHEN PRICE CROSSES ABOVE SMA(50) BUY 25%\nWHEN PRICE CROSSES BELOW SMA(50) SELL 100%"},
  {id:"long-regime",title:"Long regime",description:"100-day moving-average trend.",code:"WHEN PRICE ABOVE SMA(100) BUY 20%\nWHEN PRICE BELOW SMA(100) SELL 100%"},
  {id:"rsi-swing",title:"RSI swing",description:"Shorter RSI mean-reversion signal.",code:"WHEN RSI(9) BELOW 35 BUY 15%\nWHEN RSI(9) ABOVE 65 SELL 100%"},
  {id:"small-position",title:"Small position trend",description:"10% available-cash entries reduce risk concentration.",code:sma(20,75,10)},
];
export const PORTFOLIO_PRESETS:StrategyPreset[]=[
  {id:"cross-asset",title:"Cross-asset trend",description:"Use first asset as a signal for the second asset.",code:""},
  {id:"diversified",title:"Multi-asset trends",description:"Independent trend signals across every asset, 10% sizing.",code:""},
  {id:"conservative",title:"Conservative allocation",description:"Small entries and full exits on each asset.",code:""},
  {id:"momentum",title:"Fast sector momentum",description:"10/30-day trend for each available asset.",code:""},
  {id:"defensive",title:"Slow sector trend",description:"50/100-day trend on available assets.",code:""},
  {id:"rsi",title:"RSI rotation",description:"Use oversold/overbought signals for each asset.",code:""},
  {id:"hedge",title:"Hedge sleeve",description:"Gated defensive holdings where a bond or gold asset is in the basket.",code:""},
  {id:"quality",title:"50-day price filter",description:"Defensive price-above-trend signals.",code:""},
];
export function portfolioPresetCode(id:string,available:string[]):string{
  const ids=Array.from(new Set(available.map(x=>x.toLowerCase()))).slice(0,10);
  if(!ids.length)return "";
  const rule=(signal:string,condition:string,side:"BUY"|"SELL",pct:number,target:string)=>
    "WHEN "+signal+" "+condition+" "+side+" "+pct+"% "+target;
  const pair=(signal:string,target:string,fast:number,slow:number,pct:number)=>[
    rule(signal,"SMA("+fast+") CROSSES ABOVE SMA("+slow+")","BUY",pct,target),
    rule(signal,"SMA("+fast+") CROSSES BELOW SMA("+slow+")","SELL",100,target)
  ];
  if(id==="cross-asset"&&ids.length>=2)return pair(ids[0],ids[1],20,50,20).join("\n");
  // Max 12 rules in the compiled DSL. Use <=6 symbols so rules remain valid.
  const chosen=ids.slice(0,6);
  if(id==="hedge"){
    const defensive=ids.filter(x=>["ief","tlt","gld","tip","shy","vab","zag"].includes(x));
    if(defensive.length){
      const candidate=defensive[0];
      const leader=ids.find(x=>x!==candidate)??candidate;
      return pair(leader,candidate,20,50,15).join("\n");
    }
  }
  return chosen.flatMap(sym=>{
    if(id==="rsi")return [
      rule(sym,"RSI(14) BELOW 30","BUY",10,sym),
      rule(sym,"RSI(14) ABOVE 70","SELL",100,sym)];
    if(id==="quality")return [
      rule(sym,"PRICE ABOVE SMA(50)","BUY",10,sym),
      rule(sym,"PRICE BELOW SMA(50)","SELL",100,sym)];
    const fast=id==="momentum"?10:id==="defensive"?50:20;
    const slow=id==="momentum"?30:id==="defensive"?100:50;
    return pair(sym,sym,fast,slow,id==="conservative"?5:10);
  }).join("\n");
}
