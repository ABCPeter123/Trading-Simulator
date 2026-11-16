import {useEffect,useState} from "react";
import {BookmarkPlus,BookOpen,Clock3,Download,Trash2} from "lucide-react";
import {deleteStrategy,listStrategies,saveStrategy} from "./strategyLibraryApi";
import type {SavedStrategy} from "./strategyLibraryApi";
import {useI18n} from "./i18n";
import "./strategyLibrary.css";

export default function StrategyLibrary({mode,runId,code,symbols,activatedCode,onLoad}:{
  mode:"single"|"portfolio";runId:string;code:string;symbols:string[];
  activatedCode:string;onLoad:(code:string)=>void;
}){
  const {t}=useI18n();
  const [name,setName]=useState("");
  const [saved,setSaved]=useState<SavedStrategy[]>([]);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [message,setMessage]=useState("");
  const [selected,setSelected]=useState<string|null>(null);
  async function refresh(){
    try{setSaved(await listStrategies(mode));}
    catch(e){setError(e instanceof Error?e.message:String(e));}
  }
  useEffect(()=>{void refresh();},[mode,activatedCode]);
  async function store(){
    if(!name.trim()||!code.trim())return;
    setBusy(true);setError("");setMessage("");
    try{
      const result=await saveStrategy({name:name.trim(),mode,code,symbols,source_run_id:runId});
      setName("");setSelected(result.id);setMessage(t("Saved as a new strategy version."));
      await refresh();
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function remove(id:string){
    if(!window.confirm(t("Delete this saved strategy version? The active simulation will not change.")))return;
    setBusy(true);setError("");setMessage("");
    try{await deleteStrategy(id);if(selected===id)setSelected(null);await refresh();}
    catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  const current=saved.find(s=>s.id===selected)??null;
  return <section className="sl-library" aria-label={t("Saved Strategy Library")}>
    <div className="sl-head"><BookOpen size={17}/><div>
      <h3>{t("Saved Strategy Library")}</h3>
      <p>{t("Keep named strategy versions and revisit previously activated strategies across sessions.")}</p>
    </div><span>{saved.length} {t("versions")}</span></div>
    <div className="sl-save">
      <label>{t("Strategy name")}
        <input maxLength={80} placeholder={t("e.g. 20/50 SMA crossover v2")}
          value={name} onChange={e=>setName(e.target.value)}/>
      </label>
      <button disabled={busy||!code.trim()||!name.trim()} onClick={()=>void store()}>
        <BookmarkPlus size={15}/>{t("Save current draft")}</button>
    </div>
    <p className="sl-help">{t("Saving a version does not activate it. Activating a new strategy automatically archives the previous version.")}</p>
    <div className="sl-list">
      {saved.length===0?<p>{t("No saved strategies yet.")}</p>:saved.map(entry=>
        <div className={"sl-item "+(selected===entry.id?"selected":"")} key={entry.id}>
          <button className="sl-item-title" onClick={()=>setSelected(selected===entry.id?null:entry.id)}>
            <strong>{entry.name}</strong>
            <small><Clock3 size={12}/>{new Date(entry.created_at).toLocaleString()} · {entry.source==="activated"?t("Auto-archived"):t("Named save")} · {entry.symbols.join(", ").toUpperCase()}</small>
          </button>
          <button className="sl-trash" disabled={busy} title={t("Delete version")} onClick={()=>void remove(entry.id)}><Trash2 size={15}/></button>
        </div>
      )}
    </div>
    {current&&<div className="sl-preview">
      <pre>{current.code}</pre>
      <button type="button" onClick={()=>{onLoad(current.code);setMessage(t("Loaded into editor as a draft. Activate separately when ready."));}}>
        <Download size={15}/>{t("Load into strategy editor")}</button>
    </div>}
    {message&&<p className="sl-message" role="status">{message}</p>}
    {error&&<p className="sl-error" role="alert">{error}</p>}
  </section>;
}
