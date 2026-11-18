import {useMemo,useState} from "react";
import {useI18n} from "./i18n";
import {compareBrokerStatement} from "./brokerReconciliationApi";
import type {NormalizedStatementTrade,ReconciliationResult} from "./brokerReconciliationApi";
import "./brokerReconciliation.css";

type Key="symbol"|"side"|"trade_date"|"quantity"|"price"|"fee"|"broker_ref"|"currency";
const fields:Key[]=["symbol","side","trade_date","quantity","price","fee","broker_ref","currency"];
const required:Key[]=["symbol","side","trade_date","quantity","price"];
const aliases:Record<Key,string[]>={
  symbol:["symbol","ticker","asset","security","stock","underlying","description"],
  side:["side","action","type","transaction type","buysell","b/s","buy/sell"],
  trade_date:["trade date","date","execution time","executed at","datetime","transaction date","time"],
  quantity:["quantity","qty","shares","filled quantity","quantity filled","number of shares"],
  price:["price","execution price","price per share","trade price","fill price","average price"],
  fee:["fee","commission","fees","commission paid","transaction fee","comm/fee"],
  broker_ref:["order id","transaction id","broker reference","reference","trade id","order number","confirmation"],
  currency:["currency","ccy","trade currency"],
};
const clean=(s:string)=>s.trim().toLowerCase().replace(/[_-]+/g," ").replace(/\s+/g," ");
function parseCsv(text:string):string[][]{
  const rows:string[][]=[];let row:string[]=[],cell="",quoted=false;
  for(let i=0;i<text.length;i++){
    const ch=text[i];
    if(quoted){
      if(ch==='"'){
        if(text[i+1]==='"'){cell+='"';i++;}
        else quoted=false;
      }else cell+=ch;
    }else if(ch==='"'){if(cell!=="")throw Error("Unexpected CSV quote");quoted=true;}
    else if(ch===","){row.push(cell);cell="";}
    else if(ch==="\r"||ch==="\n"){
      if(ch==="\r"&&text[i+1]==="\n")i++;
      row.push(cell);cell="";
      if(row.some(x=>x.trim()))rows.push(row);
      row=[];
    }else cell+=ch;
  }
  if(quoted)throw Error("Unterminated CSV quote");
  row.push(cell);if(row.some(x=>x.trim()))rows.push(row);
  return rows;
}
const number=(s:string)=>{
  const value=s.trim().replace(/[$,\s]/g,"");
  if(!value)throw Error("Missing numeric value");
  const parsed=Number(value.startsWith("(")&&value.endsWith(")")?
    "-"+value.slice(1,-1):value);
  if(!Number.isFinite(parsed))throw Error("Invalid numeric value");
  return parsed;
};
function tradeDate(input:string){
  const s=input.trim();
  const iso=s.match(/^(\d{4})-(\d\d)-(\d\d)/);
  const us=s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})/);
  const date=iso?iso[1]+"-"+iso[2]+"-"+iso[3]:
    us?us[3]+"-"+us[1].padStart(2,"0")+"-"+us[2].padStart(2,"0"):"";
  if(!date||Number.isNaN(Date.parse(date+"T12:00:00Z"))||
     new Date(date+"T12:00:00Z").toISOString().slice(0,10)!==date){
    throw Error("Date must be YYYY-MM-DD or MM/DD/YYYY");
  }
  return date;
}
function normalize(csv:string[][],mapping:Record<Key,number>){
  if(csv.length<2)throw Error("No statement rows");
  if(csv.length>1001)throw Error("Maximum 1,000 trades per comparison");
  if(required.some(key=>mapping[key]<0))throw Error("Map every required field");
  const normalized:NormalizedStatementTrade[]=[];
  for(let i=1;i<csv.length;i++){
    const row=csv[i];const get=(key:Key)=>mapping[key]>=0?(row[mapping[key]]??"").trim():"";
    const rawSide=get("side").toLowerCase().replace(/\s+/g," ");
    const side:NormalizedStatementTrade["side"]=
      ["buy","bot","b","buy to cover"].includes(rawSide)?"buy":
      ["sell","sld","s","sell short"].includes(rawSide)?"sell":
      (()=>{throw Error("Unsupported buy/sell action on row "+(i+1));})();
    const unit=get("currency").toUpperCase()||"USD";
    if(unit!=="USD")throw Error("Non-USD statement row "+(i+1));
    const amount=Math.abs(number(get("quantity")));
    const price=Math.abs(number(get("price")));
    if(!amount||!price)throw Error("Zero quantity or price on row "+(i+1));
    const ticker=get("symbol").toLowerCase();
    if(!/^[a-z0-9._-]{1,32}$/.test(ticker))throw Error("Invalid ticker on row "+(i+1));
    const fee=get("fee");const ref=get("broker_ref");
    const result:NormalizedStatementTrade={
      symbol:ticker,side,quantity:amount,price,currency:"USD",trade_date:tradeDate(get("trade_date")),
      ...(fee?{fee:Math.abs(number(fee))}:{}),
      ...(ref?{broker_ref:ref.slice(0,120)}:{}),
    };
    // Date-only imports intentionally have no invented intraday timestamp.
    normalized.push(result);
  }
  return normalized;
}
const fmt=(v:number|null)=>v==null?"N/A":v.toLocaleString(undefined,{maximumFractionDigits:2});

export default function BrokerReconciliation(){
  const {locale}=useI18n();
  const t=(en:string,zh:string)=>locale==="zh-CN"?zh:en;
  const [table,setTable]=useState<string[][]>([]);
  const [mapping,setMapping]=useState<Record<Key,number>>(
    {symbol:-1,side:-1,trade_date:-1,quantity:-1,price:-1,fee:-1,broker_ref:-1,currency:-1});
  const [result,setResult]=useState<ReconciliationResult|null>(null);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const [filename,setFilename]=useState("");
  const preview=useMemo(()=>{
    if(table.length<2)return null;
    try{return {rows:normalize(table,mapping),error:""};}
    catch(e){return {rows:[],error:e instanceof Error?e.message:String(e)};}
  },[table,mapping]);
  const ingest=async(file:File|undefined)=>{
    setResult(null);setError("");setTable([]);
    if(!file)return;
    if(file.size>2_000_000){setError(t("CSV file exceeds 2 MB.","CSV文件超过2MB。"));return;}
    try{
      const parsed=parseCsv((await file.text()).replace(/^\uFEFF/,""));
      if(!parsed.length||parsed.length>1001)throw Error("Expected a header and up to 1,000 trades");
      const headers=parsed[0].map(clean);
      const guessed={} as Record<Key,number>;
      for(const field of fields)guessed[field]=headers.findIndex(h=>aliases[field].includes(h));
      setTable(parsed);setMapping(guessed);setFilename(file.name);
    }catch(e){setError(e instanceof Error?e.message:String(e));}
  };
  const compare=async()=>{
    if(!preview||preview.error||preview.rows.length===0)return;
    setBusy(true);setError("");setResult(null);
    try{setResult(await compareBrokerStatement(preview.rows));}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  };
  return <section className="rc-panel">
    <h2>{t("Reconcile broker CSV to confirmed USD trades","券商CSV与已确认美元交易核对")}</h2>
    <p>{t("Upload a CSV locally in your browser, map its columns and compare the normalized trades to your private confirmed-fill journal. The original CSV file is never uploaded or stored. The comparison never edits broker fills.",
      "在浏览器中本地读取CSV文件，映射列名后仅把标准化交易字段发送到私人API，与已确认的成交记录比对。原始CSV不会上传或存储，核对不会修改任何成交。")}</p>
    <label className="rc-file">{t("Select a USD broker trade CSV","选择美元交易CSV")}
      <input type="file" accept=".csv,text/csv" onChange={e=>void ingest(e.target.files?.[0])}/>
    </label>
    {!!filename&&<p><strong>{filename}</strong> · {Math.max(0,table.length-1)} {t("input records","条输入记录")}</p>}
    {table.length>1&&<>
      <div className="rc-maps">{fields.map(field=><label key={field}>
        {field.replaceAll("_"," ")} {required.includes(field)?"*":""}
        <select value={mapping[field]} onChange={e=>{
          setResult(null);setMapping(previous=>({...previous,[field]:Number(e.target.value)}));
        }}>
          <option value={-1}>{t("Not mapped","不映射")}</option>
          {table[0].map((value,i)=><option key={i} value={i}>{value||"Column "+(i+1)}</option>)}
        </select></label>)}</div>
      <p>{t("Date-only files match by New York trade date, not exact timestamp. Unmapped fees remain unknown, not zero.",
        "只有日期的文件按纽约交易日核对，不假定具体成交时间。没有映射的手续费视为未知，而非零。")}</p>
      {preview?.error&&<p role="alert" className="rc-error">{preview.error}</p>}
      {preview&&!preview.error&&<p>{t("Normalized rows ready: ","已标准化交易行：")}{preview.rows.length}</p>}
      <button disabled={busy||!!preview?.error||!preview?.rows.length} onClick={()=>void compare()}>
        {busy?t("Comparing...","核对中..."):t("Compare with private confirmed journal","与私人已确认交易核对")}
      </button>
    </>}
    {error&&<p role="alert" className="rc-error">{error}</p>}
    {result&&<>
      <h3>{t("Comparison results","核对结果")}</h3>
      <div className="rc-stats">
        <div><small>{t("Exact matches","完全一致")}</small><strong>{result.summary.matched}</strong></div>
        <div><small>{t("Matched with differences","已匹配但存在差异")}</small><strong>{result.summary.matched_with_differences}</strong></div>
        <div><small>{t("Not in journal","未在交易日志找到")}</small><strong>{result.summary.not_in_journal}</strong></div>
        <div><small>{t("Ambiguous","存在歧义")}</small><strong>{result.summary.ambiguous}</strong></div>
        <div><small>{t("Duplicate rows","重复对账行")}</small><strong>{result.summary.duplicate_statement_rows}</strong></div>
        <div><small>{t("Journal trades absent from this import","此批CSV未包含的交易日志记录")}</small><strong>{result.summary.journal_not_in_import}</strong></div>
      </div>
      <p>{t("Imported date range","导入日期范围")}: {result.date_range.start} - {result.date_range.end}</p>
      <div className="rc-scroll"><table><thead><tr>
        <th>{t("CSV row","CSV行")}</th><th>{t("Trade","交易")}</th>
        <th>{t("Status","状态")}</th><th>{t("Differences","差异")}</th>
        <th>{t("CSV quantity / journal","CSV数量 / 日志")}</th>
        <th>{t("CSV price / journal","CSV价格 / 日志")}</th>
        <th>{t("CSV fee / journal","CSV手续费 / 日志")}</th>
      </tr></thead><tbody>{result.reviews.map(review=><tr key={review.statement_row}>
        <td>{review.statement_row}</td>
        <td>{review.symbol.toUpperCase()} {review.side.toUpperCase()}<small>{review.trade_date}</small></td>
        <td>{review.status.replaceAll("_"," ")}</td>
        <td>{review.differences.join(", ")||"none"}</td>
        <td>{fmt(review.statement_quantity)} / {fmt(review.journal_quantity)}</td>
        <td>{fmt(review.statement_price)} / {fmt(review.journal_price)}</td>
        <td>{fmt(review.statement_fee)} / {fmt(review.journal_fee)}</td>
      </tr>)}</tbody></table></div>
      <p>{t("Results are read-only. A partial CSV export may omit trades; no absence proves an execution is missing. Review journal corrections manually, retaining revision history.",
        "核对结果只读。部分CSV可能漏含其他交易，缺失不代表券商未成交。如需修改日志，请手动操作并保留修订历史。")}</p>
    </>}
  </section>;
}
