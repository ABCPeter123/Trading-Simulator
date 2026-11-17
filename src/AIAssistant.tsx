import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Bot, Check, Copy, LoaderCircle, RefreshCcw, Send, ShieldCheck, Sparkles, X } from "lucide-react";
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
  const [selectedModel,setSelectedModel]=useState("");
  const [open,setOpen]=useState(false);
  const chatInput=useRef<HTMLTextAreaElement>(null);
  useEffect(()=>{
    if(!open)return;
    chatInput.current?.focus();
    const onKey=(event:KeyboardEvent)=>{if(event.key==="Escape")setOpen(false);};
    window.addEventListener("keydown",onKey);
    return()=>window.removeEventListener("keydown",onKey);
  },[open]);
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
    void getAIStatus().then(next=>{if(alive){setStatus(next);setSelectedModel(next.model);}})
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
      const result=await askAI(mode,runId,question,history,locale,
        status?.provider==="llama_cpp" ? selectedModel : undefined);
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

  return createPortal(<div className="ai-floating">
    <button type="button" className="ai-float-trigger"
      aria-expanded={open} aria-controls="trading-ai-chat-panel"
      aria-label={t(open?"Close AI chat":"Open AI chat")}
      onClick={()=>setOpen(value=>!value)}>
      {open?<X size={21}/>:<Bot size={22}/>}
      <span>{t("AI Strategy Assistant")}</span>
      <span className={"ai-float-state"+(status?.ready?" ready":"")} aria-hidden="true"/>
    </button>
    {open&&<section id="trading-ai-chat-panel" role="dialog" aria-modal="false"
      className="ai-box ai-popup" aria-label={t("AI Strategy Assistant")}>
    <div className="ai-head">
      <span className="ai-bot-icon"><Bot size={19}/></span>
      <div>
        <h2>{t("AI Strategy Assistant")}</h2>
        <p>{t("Ask about your actual replay results, or request an editable trading strategy.")}</p>
      </div>
      <button type="button" className="ai-close" aria-label={t("Close AI chat")} onClick={()=>setOpen(false)}><X size={18}/></button>
      <span className="ai-chip">{status?.provider==="openai"?"OpenAI":status?.provider==="ollama"?"Ollama":status?.provider==="llama_cpp"?"llama.cpp":t("Not configured")} · {status?.loaded?t("Model loaded"):status?.warming?t("Loading model"):status?.ready?t("Connected"):t("Not ready")}</span>
    </div>
    <div className="ai-status">
      <ShieldCheck size={14}/>
      <span>{status?.description ? (status.provider==="ollama"&&!status.ready
        ? `${t("Ollama is unavailable or the model is missing. Run:")} ollama pull ${status.model}` : status.provider==="ollama"
        ? status.warming?t("Ollama is preloading the model locally."):status.loaded?t("Ollama is loaded and ready for research."):t("Ollama runs locally. Install Ollama and pull the model to ask questions.")
        : status.provider==="llama_cpp"
        ? status.ready?t("The selected llama.cpp model runs locally. AI output still requires validation."):t("Start the llama.cpp router with a supported GGUF model on port 8081.")
        : status.provider==="openai"
        ? t("OpenAI runs remotely. Each question sends summarized historical game data.")
        : t("AI is disabled.")) : t("Checking AI connection...")}</span>
      {status?.provider==="llama_cpp"&&status.available_models&&status.available_models.length>0&&
        <label className="ai-model-picker">
          <span>{locale==="zh-CN"?"本地模型":"Local model"}</span>
          <select aria-label={locale==="zh-CN"?"选择本地AI模型":"Select local AI model"}
            value={selectedModel} disabled={busy}
            onChange={event=>{
              const next=event.target.value;
              setSelectedModel(next);
              setStatus(previous=>previous?{...previous,model:next,ready:false,loaded:false}:previous);
              void getAIStatus(next).then(setStatus)
                .catch(e=>setStatusError(e instanceof Error?e.message:"AI model unavailable."));
            }}>
            {status.available_models.map(model=><option key={model} value={model}>{model.includes("TwIL")?"TwIL-8B":model.includes("Qwen")?"Qwen 3.5 9B":model}</option>)}
          </select>
        </label>}
      {status?.model&&<strong>{status.model}</strong>}
      {(status?.provider==="ollama"||status?.provider==="llama_cpp")&&<button className="ai-refresh" type="button" onClick={()=>void getAIStatus(status?.provider==="llama_cpp" ? selectedModel : undefined).then(setStatus).catch(e=>setStatusError(e instanceof Error?e.message:t("AI status unavailable.")))}><RefreshCcw size={13}/>{t("Recheck AI")}</button>}
    </div>
    {statusError&&<p role="alert" className="ai-error">{t(statusError)}</p>}
    {!status?.ready&&status&&<p className="ai-setup">{status.provider==="ollama"
      ? t("Backend is still using Ollama. Set TRADING_SIM_AI_PROVIDER=llama_cpp in .env and restart the local backend.")
      : status.provider==="llama_cpp"
      ? t("Check the llama.cpp router on port 8081, then restart the local backend and recheck AI.")
      : t("Configure the backend AI provider to enable questions. See the AI setup guide.")}</p>}
    <div className="ai-suggestions">
      {suggestions.map((question,i)=><button key={i} type="button" disabled={busy||status?.ready===false}
        onClick={()=>void send(question)}><Sparkles size={13}/>{question}</button>)}
    </div>
    {turns.length>0&&<div className="ai-conversation" aria-live="polite">
      {turns.map((turn,i)=><div className={"ai-turn "+turn.role} key={i}>
        <span>{turn.role==="user"?t("You"):t("Research assistant")}</span>
        <p>{turn.content}</p>
        {turn.role==="assistant"&&answers[Math.floor(i/2)]?.warning&&
          <p className="ai-warning">{t(answers[Math.floor(i/2)].warning ?? "")}</p>}
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
    {busy&&<p className="ai-processing" role="status">{t("Local AI is processing your request.")} {elapsed}s · {status?.provider==="llama_cpp" ? (locale==="zh-CN"?"模型加载和推理可能需要更长时间。":"Loading and reasoning may take longer on the first request.") : t("First response may take longer while Ollama loads the model.")}</p>}
    {error&&<div role="alert" className="ai-error">{t(error)}{retryQuestion&&<button type="button" disabled={busy||!status?.ready} onClick={()=>void send(retryQuestion)}><RefreshCcw size={14}/>{t("Retry question")}</button>}</div>}
    <form className="ai-form" onSubmit={e=>{e.preventDefault();void send(message);}}>
      <textarea ref={chatInput} rows={2} maxLength={1200} value={message} onChange={e=>setMessage(e.target.value)}
        placeholder={t("Ask me to analyze performance or suggest a strategy...")}
        disabled={busy||status?.configured===false}/>
      <button type="submit" disabled={!message.trim()||busy||!status?.ready}>
        {busy?<LoaderCircle size={17} className="ai-spin"/>:<Send size={17}/>}
        {busy?t("Thinking..."):t("Ask AI")}
      </button>
    </form>
    <p className="ai-footnote">{t("Read-only historical analysis. AI suggestions are not guaranteed and require your explicit approval.")}</p>
    </section>}
  </div>, document.body);
}
