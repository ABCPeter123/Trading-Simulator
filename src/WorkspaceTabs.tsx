import { useI18n } from "./i18n";
import "./workspaceTabs.css";

export type WorkspaceTab = "overview"|"market"|"execution"|"strategy"|"analytics"|"scenarios"|"history";
export const WORKSPACE_TABS: WorkspaceTab[] = ["overview","market","execution","strategy","analytics","scenarios","history"];
const label:Record<WorkspaceTab,string> = {
  overview:"Historical Replay",market:"Market Data & Paper",execution:"Orders & Positions",strategy:"Strategy & AI",
  analytics:"Performance Analytics",scenarios:"Scenario Research",history:"Trade History",
};
export default function WorkspaceTabs({active,onChange}:{
  active:WorkspaceTab;onChange:(next:WorkspaceTab)=>void;
}) {
  const {t}=useI18n();
  return <nav className="ts-workspace-tabs" aria-label={t("Workspace sections")}>
    <label className="ts-mobile-section">
      <span>{t("Workspace sections")}</span>
      <select aria-label={t("Workspace sections")} value={active}
        onChange={event=>onChange(event.currentTarget.value as WorkspaceTab)}>
        {WORKSPACE_TABS.map(tab=><option key={tab} value={tab}>{t(label[tab])}</option>)}
      </select>
    </label>
    {WORKSPACE_TABS.map(tab=><button type="button" key={tab}
      aria-current={active===tab?"page":undefined}
      className={active===tab?"selected":""} onClick={()=>onChange(tab)}>{t(label[tab])}</button>)}
  </nav>;
}
