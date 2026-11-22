import {useEffect,useState} from "react";
import {request} from "./api";
import {useI18n} from "./i18n";

type BackfillJob={
 id:string;status:"queued"|"running"|"completed"|"failed"|"cancelled";
 params:{symbols:string[];start_date:string;end_date:string;resolution:string;estimated_download:string};
 stage:string;error_code:string|null;progress:number;processed_days:number;total_days:number;
};
type DailyTone={
 symbol:string;news_day:string;archive_research_available_utc:number;
 rows_scanned:number;namesets:number;mentions:number;
 raw_tone:number|null;score:number|null;status:"observed_tone"|"no_entity_match";
};
type HistoricCoverage={
 source:string;earliest_supported_date:string;requested_days:number;
 symbols:string[];coverage_days_by_symbol:Record<string,number>;
 daily:DailyTone[];live_eligible:false;limitations:string;
};
const getErr=(err:unknown)=>err instanceof Error?err.message:String(err);

export default function HistoricalNewsPanel(){
  const {locale}=useI18n();
  const l=(en:string,zh:string)=>locale==="zh-CN"?zh:en;
  const [tickers,setTickers]=useState("nvda");
  const [start,setStart]=useState("2020-03-01");
  const [end,setEnd]=useState("2020-03-07");
  const [job,setJob]=useState<BackfillJob|null>(null);
  const [data,setData]=useState<HistoricCoverage|null>(null);
  const [working,setWorking]=useState(false);
  const [error,setError]=useState("");
  const symbols=tickers.split(",").map(x=>x.trim().toLowerCase()).filter(Boolean);
  const historyUrl="/live/research/news/history?symbols="+encodeURIComponent(symbols.join(","))+
    "&start_date="+encodeURIComponent(start)+"&end_date="+encodeURIComponent(end);
  async function readHistory(){
    const result=await request<HistoricCoverage>(historyUrl);
    if(!result||!Array.isArray(result.daily))throw new Error("Historical news archive not available");
    setData(result);
  }
  async function backfill(){
    setError("");setWorking(true);setData(null);
    try{
      const found=await request<BackfillJob>("/live/research/news/history/jobs",{
        method:"POST",body:JSON.stringify({symbols,start_date:start,end_date:end})});
      if(!found||!found.id)throw new Error("Historical job could not be queued");
      setJob(found);
    }catch(e){setError(getErr(e))}
    finally{setWorking(false)}
  }
  useEffect(()=>{
    if(!job||!["queued","running"].includes(job.status))return;
    let active=true;
    const id=job.id;
    const timer=window.setInterval(()=>{
      void request<BackfillJob>("/live/research/news/history/jobs/"+encodeURIComponent(id))
        .then(updated=>{
          if(!active||!updated||updated.id!==id)return;
          setJob(updated);
          if(updated.status==="completed")void readHistory().catch(e=>{if(active)setError(getErr(e))});
        })
        .catch(e=>{if(active)setError(getErr(e))});
    },5000);
    return ()=>{active=false;window.clearInterval(timer)};
  // URL and selected dates are frozen when the queued job is started.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[job?.id,job?.status]);
  async function cancel(){
    if(!job)return;
    try{
      const result=await request<BackfillJob>(
        "/live/research/news/history/jobs/"+encodeURIComponent(job.id)+"/cancel",{method:"POST"});
      setJob(result);
    }catch(e){setError(getErr(e))}
  }
  async function read(){
    setError("");setWorking(true);
    try{await readHistory()}catch(e){setError(getErr(e))}
    finally{setWorking(false)}
  }
  return <details className="ur-advanced" style={{marginTop:12}}>
    <summary>{l("Older news archive · daily GKG back to 2013","历史新闻归档 · 每日GKG可追溯至2013年")}</summary>
    <p>{l("GDELT provides free daily historical Global Knowledge Graph archives beginning April 1, 2013. These records contain company/organization mentions and aggregate document tone, NOT original headline text. Data are retrospective and excluded from live signals.",
      "GDELT自2013年4月1日起提供免费的每日全球知识图谱历史归档。数据包含公司及组织提及次数与汇总的文章语气评分，不包含原始新闻标题。回溯数据不会用于实时信号。")}</p>
    <div className="ur-setup" style={{display:"flex",gap:10,flexWrap:"wrap",alignItems:"flex-end"}}>
      <label>{l("Stock symbols, max five","股票代码，最多五只")}
        <input type="text" value={tickers} onChange={e=>setTickers(e.target.value)}
          placeholder="nvda,tsla,amd"/></label>
      <label>{l("From (2013 or later)","开始日期（2013年以后）")}
        <input type="date" min="2013-04-01" value={start} onChange={e=>setStart(e.target.value)}/></label>
      <label>{l("Through (31 days maximum)","结束日期（最多31天）")}
        <input type="date" min="2013-04-01" value={end} onChange={e=>setEnd(e.target.value)}/></label>
      <button type="button" className="ur-secondary" disabled={working||Boolean(job&&["queued","running"].includes(job.status))}
        onClick={()=>void backfill()}>{l("Queue historical download","加入历史下载任务")}</button>
      <button type="button" className="ur-secondary" disabled={working} onClick={()=>void read()}>
        {l("View locally archived dates","查看已归档日期")}</button>
    </div>
    <p className="ur-subtitle">{l(
      "Downloads can reach 15–40 MB per day, so each queue job is capped at 31 calendar days. Pick a past month, then submit the next month to extend coverage. The private research worker runs downloads and keeps only derived company tone locally. Original ZIP files are deleted.",
      "每天的压缩下载文件可能达到15至40 MB，因此每个任务最多处理31个日历日。先选择一个历史月份，再按月分批扩展。由私人研究工作进程下载，仅保留本地公司情绪汇总，原始压缩包处理后删除。")}</p>
    {job&&<div aria-live="polite">
      <p><strong>{l("Download status","下载状态")}: {job.status}</strong> · {job.stage} ·
        {" "+job.processed_days}/{job.total_days} {l("days","天")} ({job.progress}%)</p>
      {job.error_code&&<p role="alert">{l("Historical provider did not return a valid archive. Existing days remain saved. Retry by starting the same range again.","历史数据源未返回有效归档。此前已处理日期仍保留，可重新提交相同日期范围。")}</p>}
      {["queued","running"].includes(job.status)&&<button type="button" className="ur-secondary"
        onClick={()=>void cancel()}>{l("Cancel remaining downloads","取消余下下载")}</button>}
    </div>}
    {error&&<p className="ops-error" role="alert">{error}</p>}
    {data&&<>
      <p>{l("Local GKG coverage","本地GKG覆盖")}:
        {" "+Object.entries(data.coverage_days_by_symbol).map(([sym,days])=>
          sym.toUpperCase()+" "+days+"/"+data.requested_days).join(" · ")}
      </p>
      {data.daily.length===0?
        <p>{l("No downloaded historical days match this range. Queue a download first.",
          "本地尚无该日期范围的历史新闻数据，请先创建下载任务。")}</p>:
      <div className="ur-scroll"><table>
        <thead><tr>
          <th>{l("News date","新闻日期")}</th><th>{l("Stock","股票")}</th>
          <th>{l("Normalized tone","标准化情绪")}</th>
          <th>{l("Namesets","组织关系组数")}</th>
          <th>{l("Document mentions","文档提及数")}</th>
          <th>{l("Research usable at (ET)","研究可用时间（美东）")}</th>
        </tr></thead>
        <tbody>{data.daily.map(d=><tr key={d.symbol+":"+d.news_day}>
          <td>{d.news_day}</td><td>{d.symbol.toUpperCase()}</td>
          <td>{d.score==null?l("No matching organizations","未识别该组织"):d.score.toFixed(3)}</td>
          <td>{d.namesets}</td><td>{d.mentions}</td>
          <td>{new Date(d.archive_research_available_utc*1000).toLocaleString(
            locale==="zh-CN"?"zh-CN":"en-CA",{timeZone:"America/New_York"})}</td>
        </tr>)}</tbody>
      </table></div>}
      <p className="ur-subtitle">{l(
        "Backfilled tone is available only for research after the original daily archive's conservative two-day availability lag. Missing company mentions produce no signal, not zero tone. These numbers have not been validated as profitable trading predictors.",
        "回填语气评分只能在原始归档日期之后至少两天用于历史研究。没有公司提及不会被当作中性0分。这些分数尚未证明能预测交易收益。")}</p>
    </>}
  </details>;
}
