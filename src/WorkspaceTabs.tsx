import { useI18n } from "./i18n";
import "./workspaceTabs.css";

export type WorkspaceTab = "overview"|"execution"|"strategy"|"analytics"|"scenarios"|"history";
export const WORKSPACE_TABS: WorkspaceTab[] = ["overview","execution","strategy","analytics","scenarios","history"];
const label:Record<WorkspaceTab,string> = {
  overview:"Market Overview",execution:"Orders & Positions",strategy:"Strategy & AI",
  analytics:"Performance Analytics",scenarios:"Scenario Research",history:"Trade History",
};
export default function WorkspaceTabs({active,onChange}:{
  active:WorkspaceTab;onChange:(next:WorkspaceTab)=>void;
}) {
  const {t}=useI18n();
  return <nav className="ts-workspace-tabs" aria-label={t("Workspace sections")}>
    {WORKSPACE_TABS.map(tab=><button type="button" key={tab}
      aria-current={active===tab?"page":undefined}
      className={active===tab?"selected":""} onClick={()=>onChange(tab)}>{t(label[tab])}</button>)}
  </nav>;
}
