import {useCallback,useEffect,useState} from "react";
import {useI18n} from "./i18n";
import {getExecutionWindows,checkExecutionWindows} from "./executionWindowApi";
import type {ExecutionWindowObservation} from "./executionWindowApi";
import "./executionWindows.css";

type ActualReview={signal_id:string;actual_price:number;execution_delay_hours:number;side:string;asset_id:string};
const readable=(n:number|null,suffix="")=>
  n==null||!Number.isFinite(n)?"N/A":n.toLocaleString(undefined,{maximumFractionDigits:2})+suffix;

export default function ExecutionWindowMonitor({actualReviews=[]}:{actualReviews?:ActualReview[]}){
  const {locale}=useI18n();
  const say=(en:string,zh:string)=>locale==="zh-CN"?zh:en;
  const [rows,setRows]=useState<ExecutionWindowObservation[]>([]);
  const [loading,setLoading]=useState(false);
  const [failure,setFailure]=useState("");
  const [lastCheck,setLastCheck]=useState("");
  const refresh=useCallback(async()=>{setRows(await getExecutionWindows());},[]);
  useEffect(()=>{
    let alive=true;
    void refresh().catch(()=>{});
    const interval=window.setInterval(()=>{if(alive)void refresh().catch(()=>{});},30000);
    return()=>{alive=false;window.clearInterval(interval);};
  },[refresh]);
  const check=async()=>{
    if(loading)return;
    setLoading(true);setFailure("");setLastCheck("");
    try{
      const result=await checkExecutionWindows();
      await refresh();
      setLastCheck(say("Signals checked: ","已检查信号：")+result.evaluated_signals+
        "; "+say("feed errors: ","数据错误：")+result.data_unavailable);
    }catch(err){setFailure(err instanceof Error?err.message:String(err));}
    finally{setLoading(false);}
  };
  const status=(s:string)=>({
    capacity_observed:say("Illustrative full bar capacity","单根K线推算容量充足"),
    partial_capacity_observed:say("Illustrative partial capacity","单根K线推算容量不足"),
    awaiting_completed_bar:say("Awaiting a completed candle","等待已完成K线"),
    no_completed_bar_observed:say("No eligible completed candle observed","未观察到符合窗口的已完成K线"),
    volume_unavailable:say("Volume unavailable","成交量不可用"),
    notional_unavailable:say("Order size unavailable","建议金额不可用")
  } as Record<string,string>)[s]??s;
  return <section className="ew-monitor">
    <div className="ew-heading"><h2>{say("12-hour execution-window evidence","12小时执行窗口观测")}</h2>
      <button type="button" disabled={loading} onClick={()=>void check()}>
        {loading?say("Checking...","检查中..."):say("Check five-minute data","检查五分钟行情")}
      </button>
    </div>
    <p>{say("Observed 5-minute regular-session candles, measured from signal creation. Compare modeled entry opportunities after 5, 30 and 60 minutes. No broker orders are sent. A bar open and its volume cannot prove an actual fill.",
      "根据推荐信号生成时间，使用常规交易时段已完成的5分钟K线，比较5、30、60分钟后的假设成交容量。系统不会向券商下单；开盘价和成交量不能证明真实成交。")}</p>
    {failure&&<p className="ew-error" role="alert">{failure}</p>}
    {lastCheck&&<p role="status">{lastCheck}</p>}
    {!rows.length&&<p>{say("No completed execution observations recorded yet. Start live signal monitoring, then inspect new signals.",
      "尚无执行窗口观测。请先启动实时信号监控，再查看新信号。")}</p>}
    <div className="ew-stack">
      {rows.slice(0,20).map(item=>{
        const actual=actualReviews.find(x=>x.signal_id===item.signal_id);
        return <article key={item.signal_id} className="ew-entry">
          <div className="ew-top">
            <strong>{item.symbol.toUpperCase()} · {item.side.toUpperCase()}</strong>
            <small>{say("Signal","信号时间")}: {new Date(item.signal_at).toLocaleString()} ·
              {say("Valid until","有效期至")}: {new Date(item.window_end).toLocaleString()}</small>
            <small>{item.status==="window_active"?say("Window active","窗口进行中"):
              say("Window elapsed","窗口已结束")}</small>
          </div>
          {actual&&<p>{say("Manually confirmed trade","手动确认的真实成交")}: {readable(actual.actual_price)} USD,
            {say("recorded delay","记录延迟")} {readable(actual.execution_delay_hours)}h.
            {" "}{say("This is distinct from estimated capacity.","这与估算成交容量分开记录。")}</p>}
          <div className="ew-scroll"><table><thead><tr>
            <th>{say("Minimum delay","最低延迟")}</th>
            <th>{say("Observation","观测状态")}</th>
            <th>{say("First eligible bar","首根符合条件的K线")}</th>
            <th>{say("Price USD","估计价美元")}</th>
            <th>{say("Max modeled shares","假设最多成交股数")}</th>
            <th>{say("Requested shares","建议股数")}</th>
            <th>{say("Price vs reference","相对参考价")}</th>
          </tr></thead><tbody>{item.scenarios.map(row=><tr key={row.delay_minutes}>
            <td>{row.delay_minutes}m</td><td>{status(row.status)}
              {row.retrospective&&<small>{say("Retrospective candle","事后读取K线")}</small>}</td>
            <td>{row.first_bar?new Date(row.first_bar).toLocaleString():"N/A"}</td>
            <td>{readable(row.estimated_price_usd)}</td>
            <td>{row.estimated_fillable_shares??"N/A"}
              {row.capacity_pct!=null&&<small>{readable(row.capacity_pct,"%")}</small>}</td>
            <td>{row.requested_shares??"N/A"}</td>
            <td>{readable(row.price_change_pct,"%")}</td>
          </tr>)}</tbody></table></div>
        </article>;
      })}
    </div>
    <p className="ew-note">{say("The 1% bar-volume cap, fixed indicative spread and 8 bps slippage are research assumptions. Provider gaps, holidays, after-hours markets and broker-specific execution constraints are not verified. Actual performance uses the separate manually confirmed journal.",
      "单根K线成交量1%上限、估算点差和8基点滑点均为研究假设。不验证券商实际执行、节假日、盘后交易或数据缺口。真实交易以独立的手动确认记录为准。")}</p>
  </section>;
}
