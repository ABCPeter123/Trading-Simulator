import { useEffect, useState } from "react";
import { Bot, Check, Copy, LoaderCircle, RefreshCcw, Send, ShieldCheck, Sparkles } from "lucide-react";
import { askAI, getAIStatus } from "./aiAssistantApi";
import type { AIAnswer, AIMode, AIMessage, AIStatus } from "./aiAssistantApi";
import { useI18n } from "./i18n";
import "./aiAssistant.css";

const sampleQuestions = [
  "Analyze my current strategy and explain its risks.",
  "Suggest a simple SMA crossover strategy for this game.",
  "Why did my strategy underperform buy-and-hold?",
  "What does my drawdown and trade history tell me?",
];

export default function AIAssistant({mode,runId,onDraft}: {
  mode:AIMode;runId:string;onDraft:(code:string)=>void;
}) {
  const {t,locale}=useI18n();
  const [status,setStatus]=useState<AIStatus|null>(null);
  const [statusError,setStatusError]=useState("");
  const [message,setMessage]=useState("");
  const [turns,setTurns]=useState<AIMessage[]>([]);
  const [answers,setAnswers]=useState<AIAnswer[]>([]);
  const [busy,setBusy]=useState(false);
  const [elapsed,setElapsed]=useState(0);
  const [error,setError]=useState("");
  const [retryQuestion,setRetryQuestion]=useState("");

  useEffect(()=>{
    let alive=true;
    void getAIStatus().then(next=>{if(alive)setStatus(next);})
      .catch(err=>{if(alive)setStatusError(err instanceof Error?err.message:"AI status unavailable.");});
    return ()=>{alive=false;};
    // Status reports preload progress; refresh while model is warming.
  },[]);

  useEffect(()=>{
    if(!status?.warming)return;
    const timer=setInterval(()=>{void getAIStatus().then(setStatus).catch(()=>{});},6000);
    return ()=>clearInterval(timer);
  },[status?.warming]);

  async function send(value:string) {
    const question=value.trim();
    if(!question||busy)return;
    const history=turns.slice(-6);
    setBusy(true);setElapsed(0);setError("");setRetryQuestion("");setMessage("");
    try {
      const result=await askAI(mode,runId,question,history,locale);
      setTurns(prev=>[...prev,{role:"user",content:question},{role:"assistant",content:result.answer}]);
      setAnswers(prev=>[...prev,result]);
    } catch(e) {
      setMessage(previous=>previous.trim()?previous:question);
      setRetryQuestion(question);
      setError(e instanceof Error?e.message:"AI request failed.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(()=>{
    if(!busy){return;}
    const started=Date.now();
    const ticker=setInterval(()=>setElapsed(Math.floor((Date.now()-started)/1000)),1000);
    return ()=>clearInterval(ticker);
  },[busy]);

  const suggestions = locale==="zh-CN"
    ? [
        "分析我当前策略的收益和风险。",
        "给我推荐一个简单的SMA交叉策略。",
        "为什么我的策略跑输了买入并持有？",
        "根据交易和回撤历史提出改进建议。",
      ]
    : sampleQuestions;

  return <section className="ai-box" aria-label={t("AI Strategy Assistant")}>
    <div className="ai-head">
      <span className="ai-bot-icon"><Bot size={19}/></span>
      <div>
        <h2>{t("AI Strategy Assistant")}</h2>
        <p>{t("Ask about your actual replay results, or request an editable trading strategy.")}</p>
      </div>
      <span className="ai-chip">{status?.provider==="openai"?"OpenAI":status?.provider==="ollama"?"Ollama":t("Not configured")} · {status?.loaded?t("Model loaded"):status?.warming?t("Loading model"):status?.ready?t("Connected"):t("Not ready")}</span>
    </div>
    <div className="ai-status">
      <ShieldCheck size={14}/>
      <span>{status?.description ? (status.provider==="ollama"&&!status.ready
        ? `${t("Ollama is unavailable or the model is missing. Run:")} ollama pull ${status.model}` : status.provider==="ollama"
        ? status.warming?t("Ollama is preloading the model locally."):status.loaded?t("Ollama is loaded and ready for research."):t("Ollama runs locally. Install Ollama and pull the model to ask questions.")
        : status.provider==="openai"
        ? t("OpenAI runs remotely. Each question sends summarized historical game data.")
        : t("AI is disabled.")) : t("Checking AI connection...")}</span>
      {status?.model&&<strong>{status.model}</strong>}
      {status?.provider==="ollama"&&<button className="ai-refresh" type="button" onClick={()=>void getAIStatus().then(setStatus).catch(e=>setStatusError(e instanceof Error?e.message:t("AI status unavailable.")))}><RefreshCcw size={13}/>{t("Recheck AI")}</button>}
    </div>
    {statusError&&<p role="alert" className="ai-error">{statusError}</p>}
    {!status?.ready&&status&&<p className="ai-setup">{t("Configure the backend AI provider to enable questions. See the AI setup guide.")}</p>}
    <div className="ai-suggestions">
      {suggestions.map((question,i)=><button key={i} type="button" disabled={busy||status?.ready===false}
        onClick={()=>void send(question)}><Sparkles size={13}/>{question}</button>)}
    </div>
    {turns.length>0&&<div className="ai-conversation" aria-live="polite">
      {turns.map((turn,i)=><div className={"ai-turn "+turn.role} key={i}>
        <span>{turn.role==="user"?t("You"):t("Research assistant")}</span>
        <p>{turn.content}</p>
        {turn.role==="assistant"&&answers[Math.floor(i/2)]?.warning&&
          <p className="ai-warning">{answers[Math.floor(i/2)].warning}</p>}
        {turn.role==="assistant"&&answers[Math.floor(i/2)]?.proposed_strategy&&
          <div className="ai-proposal">
            <div className="ai-proposal-heading"><Check size={14}/>{t("Validated strategy proposal")}</div>
            <pre>{answers[Math.floor(i/2)].proposed_strategy}</pre>
            <div className="ai-proposal-actions">
              <button type="button" onClick={()=> {
                const candidate=answers[Math.floor(i/2)].proposed_strategy;
                if(candidate)onDraft(candidate);
              }}><Copy size={14}/>{t("Insert draft for review")}</button>
            </div>
            <small>{t("Inserting a draft does not save, arm, execute, or backtest it. Check its sizing and rules first.")}</small>
          </div>}
      </div>)}
    </div>}
    {busy&&<p className="ai-processing" role="status">{t("Local AI is processing your request.")} {elapsed}s · {t("First response may take longer while Ollama loads the model.")}</p>}
    {error&&<div role="alert" className="ai-error">{error}{retryQuestion&&<button type="button" disabled={busy||!status?.ready} onClick={()=>void send(retryQuestion)}><RefreshCcw size={14}/>{t("Retry question")}</button>}</div>}
    <form className="ai-form" onSubmit={e=>{e.preventDefault();void send(message);}}>
      <textarea rows={2} maxLength={1200} value={message} onChange={e=>setMessage(e.target.value)}
        placeholder={t("Ask me to analyze performance or suggest a strategy...")}
        disabled={busy||status?.configured===false}/>
      <button type="submit" disabled={!message.trim()||busy||!status?.ready}>
        {busy?<LoaderCircle size={17} className="ai-spin"/>:<Send size={17}/>}
        {busy?t("Thinking..."):t("Ask AI")}
      </button>
    </form>
    <p className="ai-footnote">{t("Read-only historical analysis. AI suggestions are not guaranteed and require your explicit approval.")}</p>
  </section>;
}
