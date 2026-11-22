import {useEffect,useState} from "react";
import {request} from "./api";
import {useI18n} from "./i18n";

type Score={score:number|null;direction:string;scored_headlines:number};
type Headline={title:string;url:string;domain:string;published_utc:number;first_observed_utc:number};
type Archive={latest_refresh:number|null;provider_result_count:number;headlines:Headline[]};
type Snapshot={provider:string;free:boolean;scores:Record<string,Score>;
 instruments:Record<string,Archive>;prediction_status:string;history_warning:string};
type Update={source:string;key_required:boolean;results:{symbol:string;status:string;new_articles:number;result_truncated?:boolean}[]};
const stamp=(x:number|null)=>x?new Date(x*1000).toLocaleString():"N/A";

export default function NewsSentimentPanel({symbols}:{symbols:string[]}){
  const {locale}=useI18n();
  const l=(en:string,zh:string)=>locale==="zh-CN"?zh:en;
  const names=Array.from(new Set((symbols.length?symbols:["spy","qqq","nvda"]).map(s=>s.toLowerCase()))).slice(0,5);
  const key=names.join(",");
  const [snapshot,setSnapshot]=useState<Snapshot|null>(null);
  const [update,setUpdate]=useState<Update|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  useEffect(()=>{
    let current=true;setSnapshot(null);
    void request<Snapshot>("/live/research/news/sentiment?symbols="+encodeURIComponent(key))
      .then(s=>{if(!s||!s.scores||!s.instruments||typeof s.scores!=="object"||typeof s.instruments!=="object")throw new Error("News archive response unavailable");
        if(current)setSnapshot(s);})
      .catch(e=>{if(current)setError(String(e));});
    return()=>{current=false};
  },[key]);
  const refresh=async()=>{
    setBusy(true);setError("");
    try{
      const result=await request<Update>("/live/research/news/refresh",{
        method:"POST",body:JSON.stringify({symbols:names})});
      if(!result||!Array.isArray(result.results))throw new Error("News refresh response unavailable");
      setUpdate(result);
      const fresh=await request<Snapshot>("/live/research/news/sentiment?symbols="+encodeURIComponent(key));
      if(!fresh||!fresh.scores||!fresh.instruments)throw new Error("News archive response unavailable");
      setSnapshot(fresh);
    }catch(e){setError(e instanceof Error?e.message:String(e))}
    finally{setBusy(false);}
  };
  return <details className="ur-advanced" style={{margin:"12px 0"}}>
    <summary>{l("Free news sentiment · observed headlines","免费新闻情绪 · 已观察到的新闻")}</summary>
    <p>{l("Keyless GDELT headlines are archived locally. The score is an experimental, event-aware text indicator, not a trained return forecast. Only headlines observed before the actual trade decision are usable.",
      "使用免密钥GDELT新闻，并仅存储在本地。情绪评分是实验性的事件文本指标，不是已训练的收益预测。交易只能使用决策之前已实际观察到的新闻。")}</p>
    <button className="ur-secondary" type="button" disabled={busy}
      onClick={()=>void refresh()}>{busy?l("Retrieving provider headlines","正在获取新闻"):l("Refresh free headlines","刷新免费新闻")}</button>
    <p className="ur-subtitle">{l("Each provider query is rate limited; only the first five selected instruments are scanned per refresh. No API key or subscription is required.",
      "为遵守接口限频，每次只扫描所选的前五个标的，无需API密钥或付费订阅。")}</p>
    <p className="ur-subtitle">{l("A refresh sends public company or ETF search terms to GDELT. It does not send your portfolio weights, financial accounts or private strategy reports.",
      "刷新会向GDELT发送公开公司或ETF搜索词，不会发送组合权重、金融账户或私人策略报告。")}</p>
    {error&&<p role="alert" className="ops-error">{error}</p>}
    {update&&<p role="status">{update.results.map(x=>x.symbol.toUpperCase()+": "+x.status+" (+"+x.new_articles+(x.result_truncated?", partial":"")+")").join(" · ")}</p>}
    {!snapshot?<p>{l("Reading local news archive…","读取本地新闻数据库中…")}</p>:
      <div className="ur-kpis">
        {names.map(symbol=>{
          const score=snapshot.scores?.[symbol],collection=snapshot.instruments?.[symbol];
          return <div key={symbol} style={{minWidth:0}}>
            <small>{symbol.toUpperCase()}</small>
            <strong>{score?.score==null?"N/A":score.score.toFixed(3)}</strong>
            <p>{score?.direction??"unavailable"} · {score?.scored_headlines??0}
              {" "}{l("scored headlines","条评分新闻")}</p>
            <p>{l("Last fetched","最近获取")}: {stamp(collection?.latest_refresh??null)}</p>
            {collection?.headlines?.slice(0,3).map(headline=>
              <p key={headline.url} style={{overflowWrap:"anywhere"}}>
                <a href={headline.url} target="_blank" rel="noopener noreferrer">{headline.title}</a>
                <small style={{display:"block"}}>{headline.domain} · {l("Observed","观察于")}: {stamp(headline.first_observed_utc)}</small>
              </p>)}
          </div>;
        })}
      </div>}
    <p className="ur-subtitle">{l("Historical Sharpe results do not include these headlines. Enable the optional news-risk overlay on a NEW forward-paper trial to evaluate whether reducing exposure after negative archived headlines actually helps. A headline's earlier publication date cannot make it usable before the local archive first observed it.",
      "历史夏普结果不包括这些新闻。请在新建前向模拟时选择新闻风控，以测试负面新闻之后降低敞口是否有效。即使新闻更早发布，也不能在本地首次观察之前用于历史交易。")}</p>
  </details>;
}
