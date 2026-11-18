import {useCallback,useEffect,useState} from "react";
import {request} from "./api";
import {importTournamentRank,createTournamentReplay,createCustomPeriodStudy} from "./tournamentApi";
import type {CustomPeriodJob} from "./tournamentApi";
import TournamentStrategyInspector from "./TournamentStrategyInspector";
import type {TournamentModelSpec} from "./TournamentStrategyInspector";
import {useI18n} from "./i18n";
import "./universeResearch.css";

type Metric={return_pct:number;max_drawdown_pct:number;trades:number;fees:number;turnover_pct:number;
  sharpe?:number|null;sortino?:number|null;annualized_volatility_pct?:number|null;
  peak_gross_leverage?:number;margin_interest?:number;short_borrow_cost?:number;
  margin_calls?:number;short_executions?:number;average_gross_exposure_pct?:number};
type Scenario={name:string;horizon_sessions:number;p05_return_pct:number;median_return_pct:number;p95_return_pct:number;median_max_drawdown_pct:number;
  daily?:{session:number;p05_return_pct:number;median_return_pct:number;p95_return_pct:number}[]};
type RegimeMetrics={samples:number;worst_regime_return_pct:number;
  regimes:Record<string,{observations:number;return_pct:number;positive_day_pct:number;worst_day_pct:number}>};
type ExecutionSample={time:number;symbol:string;side:string;quantity:number;price:number;fee:number;notional:number};
type ObjectiveMetrics={cagr_pct:number|null;excess_sharpe:number|null;
  annualized_volatility_pct:number|null;sessions:number};
type ValidationWindow={start:number;end:number;sessions:number;return_pct:number;
  cagr_pct:number|null;excess_sharpe:number|null};
type ValidationStability={windows:ValidationWindow[];positive_windows:number;
  window_count:number;worst_window_return_pct:number|null;
  all_windows_positive:boolean;sufficient_history:boolean};
type ScoreBreakdown={total:number;definition:string;components:Record<string,number>;eligible:boolean};
type CostAudit={explicit_total_usd:number;transaction_and_fx_usd:number;margin_interest_usd:number;
  short_borrow_usd:number;estimated_spread_usd:number;estimated_slippage_usd:number};
type Winner={rank:number;basket_type:string;symbols:string[];model:string;validation_score:number;training:Metric;
  sleeves?:{model:string;weight_pct:number}[]|null;
  score_breakdown?:ScoreBreakdown;held_out_cost_audit?:CostAudit;
  validation_execution_stress?:{return_pct:number;max_drawdown_pct:number;score:number;
    delay_sessions:number;slippage_bps:number;selection_only_validation_data:boolean}|null;
  validation_objectives?:ObjectiveMetrics;held_out_objectives?:ObjectiveMetrics;
  delayed_stress_objectives?:ObjectiveMetrics;
  validation_stability?:ValidationStability;pareto_optimal_validation?:boolean;
  held_out_target_observed?:boolean;held_out_target_evaluable?:boolean;
  validation:Metric;held_out:Metric;delayed_execution_stress:Metric;restricted_research:boolean;
  short_proxy_research:boolean;research_only?:boolean;
  validation_regimes?:RegimeMetrics;held_out_regimes?:RegimeMetrics;
  held_out_execution_sample?:ExecutionSample[];
  coverage?:{first_session:string;last_session:string;common_sessions:number};
  hypothetical_scenarios:{paths:Scenario[]};execution_model:string;scenario_calibration?:string};
type Outcome={universe_count:number;eligible_count:number;excluded_count:number;qualified_candidates:number;
  research_objective?:"balanced"|"high_performance";
  objective_targets?:{cagr_pct:number;excess_sharpe:number;risk_free_pct:number;max_drawdown_pct:number};
  pareto_candidate_count?:number;shortlist_targets_observed?:number;
  basket_count:number;candidates_evaluated:number;top10:Winner[];limitations:string[];
  basket_search?:"focused"|"expanded";selection_policy?:"return_risk"|"execution_robust";
  asset_screen?:{screen_cutoff:string|null;screened_instruments:number;
    screened_pool:number;generated_baskets:number;method:string};
  selection_method:string;execution_assumptions:Record<string,string|number>;
  candidate_model_counts?:Record<string,number>;
  historical_coverage?:{universe_earliest_session:string|null;
    universe_latest_session:string|null;method:string};
  shortlist_is_global_top_ten?:boolean};
type Job={id:string;status:"queued"|"running"|"completed"|"failed"|"cancelled";created_at:string;
  progress:number;stage:string;scanned:number;eligible:number;error_code:string|null;
  params:{scope:string;delay_sessions:1|2;max_drawdown_pct:number;max_position_pct:number;
    research_objective?:"balanced"|"high_performance";target_cagr_pct?:number;
    target_sharpe?:number;risk_free_pct?:number;
    target_investment_pct?:number;equity_class_cap_pct?:number;
    redistribute_excess?:boolean;base_currency?:"USD"|"CAD";slippage_bps?:number;
    commission_usd?:number;fx_conversion_bps?:number;include_blends?:boolean;
    basket_search?:"focused"|"expanded";selection_policy?:"return_risk"|"execution_robust"};result:Outcome|null};
import {validatedPercent} from "./validatedPercent";

const pct=(x:number)=>Number.isFinite(x)?x.toFixed(2)+"%":"N/A";
const label=(x:string)=>x.replaceAll("_"," ").replace(/\b\w/g,c=>c.toUpperCase());
export default function UniverseResearch({onOpenDiscovery,onOpenSimulation,onOpenLive}:{
  onOpenDiscovery:()=>void;onOpenSimulation:(runId:string)=>void;onOpenLive:(strategyId:string)=>void;
}){
  const {t,locale}=useI18n();
  const bilingual=(en:string,cn:string)=>locale==="zh-CN"?cn:en;
  const [scope,setScope]=useState<"all"|"etfs"|"stocks">("all");
  const [delay,setDelay]=useState<1|2>(1);
  const [baseCurrency,setBaseCurrency]=useState<"USD"|"CAD">("USD");
  const [slippage,setSlippage]=useState("8");
  const [commission,setCommission]=useState("0");
  const [fxBps,setFxBps]=useState("150");
  const [includeBlends,setIncludeBlends]=useState(true);
  const [basketSearch,setBasketSearch]=useState<"focused"|"expanded">("expanded");
  const [selectionPolicy,setSelectionPolicy]=useState<"return_risk"|"execution_robust">("execution_robust");
  const [drawdown,setDrawdown]=useState("30");
  const [weight,setWeight]=useState("35");
  const [objective,setObjective]=useState<"balanced"|"high_performance">("high_performance");
  const [targetCagr,setTargetCagr]=useState("55");
  const [targetSharpe,setTargetSharpe]=useState("2");
  const [riskFree,setRiskFree]=useState("3");
  const [targetInvestment,setTargetInvestment]=useState("100");
  const [equityLimit,setEquityLimit]=useState("100");
  const [redistributeUnused,setRedistributeUnused]=useState(true);
  const [jobs,setJobs]=useState<Job[]>([]);
  const [active,setActive]=useState<Job|null>(null);
  const [pick,setPick]=useState(0);
  const [detailTab,setDetailTab]=useState<"overview"|"validation"|"risk"|"scenarios"|"tools">("overview");
  const [busy,setBusy]=useState(false);
  const [promotionTarget,setPromotionTarget]=useState<"simulation"|"live"|"research"|null>(null);
  const [researchJob,setResearchJob]=useState<{selection:string;job:CustomPeriodJob}|null>(null);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const refresh=useCallback(async()=>{
    const rows=await request<Job[]>("/live/research/universe/jobs");
    if(!Array.isArray(rows))throw new Error("Research queue returned an invalid response.");
    setJobs(rows);
    return rows;
  },[]);
  useEffect(()=>{
    let alive=true;
    void refresh().then(rows=>{
      if(!alive||!rows.length)return;
      void request<Job>("/live/research/universe/jobs/"+encodeURIComponent(rows[0].id))
        .then(j=>{if(alive)setActive(j);}).catch(()=>{});
    }).catch(e=>{if(alive)setError(String(e));});
    return()=>{alive=false;};
  },[refresh]);
  useEffect(()=>{
    let alive=true;
    const timer=window.setInterval(()=>{
      void refresh().then(rows=>{
        const id=active?.id??rows[0]?.id;
        if(!alive||!id)return;
        void request<Job>("/live/research/universe/jobs/"+encodeURIComponent(id))
          .then(j=>{if(alive)setActive(j);}).catch(()=>{});
      }).catch(()=>{});
    },5000);
    return()=>{alive=false;window.clearInterval(timer);};
  },[refresh,active?.id]);
  async function run(){
    setBusy(true);setError("");
    try{
      const max_drawdown_pct=validatedPercent(drawdown,"Maximum validation drawdown",5,60);
      const max_position_pct=validatedPercent(weight,"Maximum position weight",10,50);
      const target_cagr_pct=validatedPercent(targetCagr,"Annual growth objective",10,100);
      const target_sharpe=validatedPercent(targetSharpe,"Excess Sharpe objective",.5,5);
      const risk_free_pct=validatedPercent(riskFree,"Risk-free annual return assumption",0,15);
      const target_investment_pct=validatedPercent(targetInvestment,"Target invested percentage",5,100);
      const equity_class_cap_pct=validatedPercent(equityLimit,"Equity class exposure limit",10,100);
      const slippage_bps=validatedPercent(slippage,"Slippage in basis points",0,100);
      const commission_usd=validatedPercent(commission,"Commission in USD",0,30);
      const fx_conversion_bps=validatedPercent(fxBps,"FX conversion in basis points",0,300);
      const job=await request<Job>("/live/research/universe/jobs",{method:"POST",
        body:JSON.stringify({scope,delay_sessions:delay,
          max_drawdown_pct,max_position_pct,research_objective:objective,
          base_currency:baseCurrency,slippage_bps,commission_usd,fx_conversion_bps,
          include_blends:includeBlends,basket_search:basketSearch,
          selection_policy:selectionPolicy,
          target_cagr_pct,target_sharpe,risk_free_pct,
          target_investment_pct:objective==="high_performance"?target_investment_pct:95,
          equity_class_cap_pct:objective==="high_performance"?equity_class_cap_pct:70,
          redistribute_excess:objective==="high_performance"&&redistributeUnused})});
      setActive(job);setPick(0);setDetailTab("overview");await refresh();
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  async function open(id:string){
    setBusy(true);setError("");
    try{
      const job=await request<Job>("/live/research/universe/jobs/"+encodeURIComponent(id));
      setActive(job);setPick(0);setDetailTab("overview");
    }catch(e){setError(String(e));}
    finally{setBusy(false);}
  }
  async function cancel(){
    if(!active)return;
    try{
      await request("/live/research/universe/jobs/"+encodeURIComponent(active.id)+"/cancel",{method:"POST"});
      await open(active.id);
    }catch(e){setError(String(e));}
  }
  async function promote(destination:"simulation"|"live"|"research"){
    if(!active||!chosen||!selectedSpec)return;
    if(chosen.research_only&&destination!=="research"){
      setError(t("Short selling and margin models require the historical research simulator, not the cash-only replay."));
      return;
    }
    setBusy(true);setPromotionTarget(destination);setError("");setNotice("");
    try{
      if(destination==="research"){
        // Runs the signed-share historical fill engine without creating a
        // cash-only replay, broker order, or live deployment.
        const job=await createCustomPeriodStudy({spec:selectedSpec});
        setResearchJob({selection:selectedKey,job});
        setDetailTab("tools");
        window.requestAnimationFrame(()=>{
          document.getElementById("ur-custom-study")?.scrollIntoView({
            behavior:"smooth",block:"start",
          });
        });
      }else{
        const version=await importTournamentRank(active.id,chosen.rank);
        if(destination==="simulation"){
          const replay=await createTournamentReplay(version.id);
          onOpenSimulation(replay.id);
        }else{
          onOpenLive(version.id);
        }
      }
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);setPromotionTarget(null);}
  }
  async function importAll(){
    if(!active||!result?.top10.length)return;
    setBusy(true);setError("");setNotice("");
    try{
      let saved=0;
      for(const winner of result.top10){
        await importTournamentRank(active.id,winner.rank);saved++;
      }
      setNotice(bilingual(`${saved} portfolio versions saved privately. Blends remain research-only and cannot trade.`,
        `已私下保存 ${saved} 个组合版本。混合策略仍仅限研究，不可交易。`));
    }catch(e){setError(e instanceof Error?e.message:String(e));}
    finally{setBusy(false);}
  }
  const result=active?.result;
  const chosen=result?.top10[pick];
  const standardModel=Boolean(chosen&&["equal_weight","inverse_volatility",
    "trend_filter","relative_momentum","volatility_target"].includes(chosen.model));
  const customResearchExposure=Boolean(standardModel&&active?.params.research_objective==="high_performance"&&(
    (active.params.target_investment_pct??95)!==95||
    (active.params.equity_class_cap_pct??70)!==70||
    Boolean(active.params.redistribute_excess)));
  const selectedKey=active&&chosen?`${active.id}:${chosen.rank}`:"";
  const selectedSpec:TournamentModelSpec|null=active&&chosen?{
    version:(["blended_portfolio","leveraged_trend","long_short_momentum","market_neutral",
      "defensive_rotation","diversified_risk_parity","equity_hedge"].includes(chosen.model)?2:1),
    model:chosen.model,symbols:chosen.symbols,
    ...(chosen.sleeves?{sleeves:chosen.sleeves}:{}),
    base_currency:active.params.base_currency??"USD",
    slippage_bps:active.params.slippage_bps??8,
    commission_usd:active.params.commission_usd??0,
    fx_conversion_bps:active.params.fx_conversion_bps??150,
    max_position_pct:active.params.max_position_pct,
    delay_sessions:active.params.delay_sessions,rebalance_sessions:21,
    restricted_research:chosen.restricted_research,
    short_proxy_research:chosen.short_proxy_research,
    research_only:chosen.research_only,
    ...((standardModel||chosen.model==="blended_portfolio")&&active.params.research_objective==="high_performance"?{
      target_investment_pct:active.params.target_investment_pct??95,
      equity_class_cap_pct:active.params.equity_class_cap_pct??70,
      redistribute_excess:Boolean(active.params.redistribute_excess)}:{}),
  }:null;
  return <main className="ur-shell">
    <header className="ur-header"><div>
      <p className="ur-kicker">{t("PRIVATE QUANTITATIVE RESEARCH")}</p>
      <h1>{t("Strategy Tournament")}</h1>
      <p>{t("Scan actual instrument history, rank the top ten portfolio strategies, and inspect delay and scenario stress. Nothing trades automatically.")}</p>
    </div></header>
    <details className="ur-workflow-help"><summary>{bilingual("How the research test works","研究测试如何进行")}</summary>
    <div className="ur-steps">{[
      ["1",t("Collect history"),t("Screen actual daily OHLCV, exclude unavailable assets.")],
      ["2",t("Compare methods"),bilingual("Test diversified baskets, advanced research models and shared-cash blends.","测试多元资产组合、进阶研究模型及共享现金的混合策略。")],
      ["3",t("Rank validation"),t("The held-out final 20% never determines the ranking.")],
      ["4",t("Stress test"),t("Inspect execution costs, extra delay and hypothetical paths.")],
    ].map(([n,title,desc])=><article key={n}><b>{n}. {title}</b><p>{desc}</p></article>)}</div>
    </details>
    {error&&<p className="ops-error" role="alert">{error}</p>}
    {notice&&<p className="ops-message" role="status">{notice}</p>}
    <div className="ur-columns">
      <section className="ur-panel ur-setup"><h2>{bilingual("Run a strategy test","运行策略测试")}</h2>
        <p className="ur-subtitle">{bilingual("Use the defaults, or adjust the essentials below.","可以使用默认设置，也可以修改以下主要选项。")}</p>
        <label>{t("Universe")}
          <select value={scope} onChange={e=>setScope(e.target.value as typeof scope)}>
            <option value="all">{t("All stocks and ETFs")}</option>
            <option value="etfs">{t("ETFs only")}</option>
            <option value="stocks">{t("Stocks only")}</option>
          </select></label>
        <label>{t("Research objective")}
          <select value={objective} onChange={e=>setObjective(e.target.value as typeof objective)}>
            <option value="high_performance">{t("High-performance discovery")}</option>
            <option value="balanced">{t("Balanced risk-adjusted ranking")}</option>
          </select></label>
        <label>{t("Maximum validation drawdown (%)")}
          <input type="number" min="5" max="60" value={drawdown} onChange={e=>setDrawdown(e.target.value)}/></label>
        <label>{t("Maximum position weight (%)")}
          <input type="number" min="10" max="50" value={weight} onChange={e=>setWeight(e.target.value)}/></label>
        <details className="ur-advanced">
          <summary>{bilingual("Advanced settings","高级设置")}</summary>
          <p className="ur-subtitle">{bilingual("Basket selection, execution costs and research targets. Changes apply to your next scan.","资产组合筛选、执行成本及研究目标。修改后将在下一次扫描中生效。")}</p>
        <div className="ur-objective-panel">
          <strong>{bilingual("Portfolio search and selection","组合搜索及筛选方法")}</strong>
          <label>{bilingual("Asset basket search breadth","资产组合搜索范围")}
            <select value={basketSearch} onChange={e=>setBasketSearch(e.target.value as "focused"|"expanded")}>
              <option value="focused">{bilingual("Focused · baseline screened baskets","精简 · 基础资产组合")}</option>
              <option value="expanded">{bilingual("Expanded · up to 16 additional training-screened baskets","扩展 · 最多增加16个仅用训练数据筛选的组合")}</option>
            </select></label>
          <label>{bilingual("Validation ranking policy","验证期排名规则")}
            <select value={selectionPolicy} onChange={e=>setSelectionPolicy(e.target.value as "return_risk"|"execution_robust")}>
              <option value="return_risk">{bilingual("Growth, Sharpe and risk","增长、夏普及风险")}</option>
              <option value="execution_robust">{bilingual("Execution robust · penalize delayed fills","执行稳健 · 惩罚延迟成交损失")}</option>
            </select></label>
          <p>{bilingual("Expanded baskets use training-only momentum, historical volatility and correlations. Robust ranking also evaluates delayed validation fills before sealing the held-out audit.",
            "扩展组合仅使用训练期动量、历史波动及相关性。稳健排名会在留出测试前，使用验证期评估延迟成交的影响。")}</p>
        </div>
        <label>{t("Signal execution delay")}
          <select value={delay} onChange={e=>setDelay(Number(e.target.value) as 1|2)}>
            <option value={1}>{t("Next session open")}</option>
            <option value={2}>{t("Second session open")}</option>
          </select></label>
        <div className="ur-objective-panel">
          <strong>{bilingual("Broker execution assumptions","经纪商执行成本假设")}</strong>
          <label>{bilingual("Funding currency","账户资金币种")}
            <select value={baseCurrency} onChange={e=>setBaseCurrency(e.target.value as "USD"|"CAD")}>
              <option value="USD">USD</option><option value="CAD">CAD</option>
            </select></label>
          <label>{bilingual("Slippage (bps per side)","单边滑点（基点）")}
            <input type="number" min="0" max="100" value={slippage} onChange={e=>setSlippage(e.target.value)}/></label>
          <label>{bilingual("Commission per trade (USD)","每笔佣金（美元）")}
            <input type="number" min="0" max="30" step="0.1" value={commission} onChange={e=>setCommission(e.target.value)}/></label>
          <label>{bilingual("FX conversion (bps on cross-currency orders)","跨币种交易换汇费（基点）")}
            <input type="number" min="0" max="300" value={fxBps} onChange={e=>setFxBps(e.target.value)}/></label>
          <label className="ur-checkbox-label"><input type="checkbox" checked={includeBlends}
            onChange={e=>setIncludeBlends(e.target.checked)}/>
            {bilingual("Search shared-cash multi-strategy blends","搜索共享现金账本的混合策略")}</label>
          <p>{bilingual("USD funding avoids simulated USD-to-CAD conversion on USD orders. Models still use estimated spreads, delayed opens and financing, not broker fills.",
            "美元账户不对美元交易模拟加元换汇。价格仍基于估算价差、延迟开盘及融资成本，并非真实成交。")}</p>
        </div>
        {objective==="high_performance"&&<div className="ur-objective-panel">
          <strong>{t("High-performance research targets")}</strong>
          <p>{t("Targets are aspirational. Ranking uses validation data only. No historical strategy can promise these results.")}</p>
          <label>{t("Target annual compound growth (%)")}
            <input type="number" min="10" max="100" step="1" value={targetCagr}
              onChange={e=>setTargetCagr(e.target.value)}/></label>
          <label>{t("Target excess Sharpe ratio")}
            <input type="number" min="0.5" max="5" step="0.1" value={targetSharpe}
              onChange={e=>setTargetSharpe(e.target.value)}/></label>
          <label>{t("Assumed annual risk-free rate (%)")}
            <input type="number" min="0" max="15" step="0.25" value={riskFree}
              onChange={e=>setRiskFree(e.target.value)}/></label>
          <label>{t("Target invested capital (%)")}
            <input type="number" min="5" max="100" step="1" value={targetInvestment}
              onChange={e=>setTargetInvestment(e.target.value)}/></label>
          <label>{t("Equity category exposure cap (%)")}
            <input type="number" min="10" max="100" step="1" value={equityLimit}
              onChange={e=>setEquityLimit(e.target.value)}/></label>
          <label className="ur-checkbox-label">
            <input type="checkbox" checked={redistributeUnused}
              onChange={e=>setRedistributeUnused(e.target.checked)}/>
            {t("Redistribute unused weight among eligible assets")}
          </label>
          <p>{t("Full-investment settings apply only to the five standard long-only models; advanced leverage and hedge models retain their own limits.")}</p>
          <p>{t("Cash rate is held constant for metric calculations; it is not credited as portfolio income.")}</p>
        </div>}
        </details>
        <button className="ur-primary" disabled={busy} onClick={()=>void run()}>{t("Run universe-wide scan")}</button>
        <details className="ur-history"><summary>{bilingual("Previous scans and other research tools","历史扫描与其他研究工具")} ({jobs.length})</summary>
        <p>{t("The laptop research worker performs all calculations. Historical data availability determines how many symbols qualify.")}</p>
        <button className="ur-secondary" onClick={onOpenDiscovery}>{t("Open individual optimizers")}</button>
        <h3>{t("Previous scans")}</h3>
        {jobs.length===0?<p>{t("No scans recorded.")}</p>:jobs.map(job=>
          <button type="button" disabled={busy} key={job.id} className="ur-job"
            onClick={()=>void open(job.id)}>
            <strong>{new Date(job.created_at).toLocaleString()}</strong>
            <span>{t(job.status)} · {job.eligible}/{job.scanned}</span>
          </button>)}
        </details>
      </section>
      <section className="ur-panel ur-results">
        {!active?<div><h2>{t("Start your first scan")}</h2>
          <p>{t("Use real backfilled data. Scans with insufficient historical coverage may produce fewer than ten results.")}</p>
        </div>:<>
          <h2>{t("Research progress")}: {t(active.status)}</h2>
          <p>{active.stage} · {active.progress}% · {active.eligible}/{active.scanned} {t("eligible")}</p>
          {(active.status==="queued"||active.status==="running")&&<>
            <div className="ur-progress" role="progressbar" aria-valuenow={active.progress}
              aria-valuemin={0} aria-valuemax={100}><i style={{width:active.progress+"%"}}/></div>
            <button className="ur-secondary" onClick={()=>void cancel()}>{t("Cancel scan")}</button>
          </>}
          {active.error_code&&<p role="alert">{active.error_code}</p>}
          {result&&<>
            <div className="ur-kpis">
              {[[t("Catalog"),result.universe_count],[t("Eligible"),result.eligible_count],
                [t("Evaluated"),result.candidates_evaluated],[t("Qualified"),result.qualified_candidates],
                [t("Ranked"),result.top10.length]].map(([name,n])=>
                <div key={String(name)}><small>{name}</small><strong>{n}</strong></div>)}
            </div>
            {result.asset_screen&&<details className="ur-score-details">
              <summary>{bilingual("Asset-screen audit and leakage safeguards","资产筛选审计及防止未来数据泄露")}</summary>
              <div className="ur-kpis">
                <div><small>{bilingual("Screen cutoff","筛选截止日期")}</small>
                  <strong>{result.asset_screen.screen_cutoff??"N/A"}</strong></div>
                <div><small>{bilingual("Eligible screen candidates","有效筛选资产")}</small>
                  <strong>{result.asset_screen.screened_instruments}</strong></div>
                <div><small>{bilingual("Risk/correlation pool","相关性分析资产池")}</small>
                  <strong>{result.asset_screen.screened_pool}</strong></div>
                <div><small>{bilingual("Generated baskets","生成的资产组合")}</small>
                  <strong>{result.asset_screen.generated_baskets}</strong></div>
              </div><p>{result.asset_screen.method}</p>
              <p>{bilingual("Asset selection does not use validation or held-out candles. The symbol catalog can still have survivorship bias.",
                "资产筛选不使用验证期或留出期价格，但标的列表仍可能存在幸存者偏差。")}</p>
            </details>}
            <p>{result.selection_method}</p>
            {result.research_objective==="high_performance"&&result.objective_targets&&<div className="ur-objective-results">
              <h3>{t("High-performance discovery results")}</h3>
              <p>{t("The target is an objective, not a prediction. Training, validation and held-out results are distinct.")}</p>
              <div className="ur-kpis">
                <div><small>{t("Annual compound growth target")}</small>
                  <strong>{pct(result.objective_targets.cagr_pct)}</strong></div>
                <div><small>{t("Excess Sharpe target")}</small>
                  <strong>{result.objective_targets.excess_sharpe.toFixed(2)}</strong></div>
                <div><small>{t("Candidates on validation Pareto frontier")}</small>
                  <strong>{result.pareto_candidate_count??0}</strong></div>
                <div><small>{t("Shortlisted candidates reaching held-out targets")}</small>
                  <strong>{result.shortlist_targets_observed??0} / {result.top10.length}</strong></div>
              </div>
              <p>{t("Held-out observations are descriptive only. A qualifying candidate needs at least 126 held-out trading sessions; meeting a target is not proof of annual consistency.")}</p>
            </div>}
            {result.historical_coverage&&<p>{t("Available historical coverage")}: {
              result.historical_coverage.universe_earliest_session??t("Unknown")} · {
              result.historical_coverage.universe_latest_session??t("Unknown")}.
              {t("Each portfolio uses only dates shared by all of its instruments.")}</p>}
            {result.candidate_model_counts&&<details><summary>{t("Models evaluated by family")}</summary>
              <div className="ur-kpis">{Object.entries(result.candidate_model_counts).map(([name,count])=>
                <div key={name}><small>{label(name)}</small><strong>{count}</strong></div>)}</div>
            </details>}
            <h2>{t("Top 10 research strategies")}</h2>
            <button type="button" className="ur-secondary" disabled={busy||!result.top10.length}
              onClick={()=>void importAll()}>{t("Save all top 10 strategy models")}</button>
            {result.top10.length===0?<p>{t("No qualifying candidates. Inspect missing history or relax the validation constraints.")}</p>:
            <div className="ur-scroll"><table><thead><tr><th>{t("Rank")}</th>
              <th>{t("Basket / Model")}</th><th>{t("Validation")}</th>
              <th>{t("Drawdown")}</th><th>{t("Held-out")}</th><th>{t("Score")}</th>
            </tr></thead><tbody>{result.top10.map((row,i)=><tr key={row.rank} className={i===pick?"ur-active":""}>
              <td><button className="ur-link" onClick={()=>setPick(i)}>#{row.rank}</button></td>
              <td><button className="ur-link" onClick={()=>setPick(i)}>{label(row.basket_type)} · {label(row.model)}</button>
                <small>{row.symbols.join(", ").toUpperCase()}</small>
                {row.sleeves&&<small>{row.sleeves.map(x=>`${label(x.model)} ${x.weight_pct}%`).join(" + ")}</small>}
                {row.research_only&&<small>{t("Synthetic short / margin research only")}</small>}</td>
              <td>{pct(row.validation.return_pct)}</td><td>{pct(row.validation.max_drawdown_pct)}</td>
              <td>{pct(row.held_out.return_pct)}</td><td>{row.validation_score.toFixed(2)}</td>
            </tr>)}</tbody></table></div>}
            {chosen&&<article className="ur-detail">
              <h3>#{chosen.rank} {label(chosen.basket_type)} · {label(chosen.model)}</h3>
              <p>{chosen.symbols.map(x=>x.toUpperCase()).join(" · ")}</p>
              {chosen.sleeves&&<p>{bilingual("Blended research sleeves","混合研究策略权重")}: {
                chosen.sleeves.map(x=>label(x.model)+" "+x.weight_pct+"%").join(" + ")}</p>}
              {chosen.validation_execution_stress&&<div className="ur-objective-results">
                <h4>{bilingual("Validation execution robustness","验证期执行稳健性")}</h4>
                <div className="ur-kpis">
                  <div><small>{bilingual("Extra-delay validation return","额外延迟验证收益")}</small>
                    <strong>{pct(chosen.validation_execution_stress.return_pct)}</strong></div>
                  <div><small>{bilingual("Delayed validation drawdown","延迟执行验证回撤")}</small>
                    <strong>{pct(chosen.validation_execution_stress.max_drawdown_pct)}</strong></div>
                  <div><small>{bilingual("Delayed ranking score","延迟执行评分")}</small>
                    <strong>{chosen.validation_execution_stress.score.toFixed(2)}</strong></div>
                  <div><small>{bilingual("Stress slippage","压力测试滑点")}</small>
                    <strong>{chosen.validation_execution_stress.slippage_bps} bps</strong></div>
                </div><p>{bilingual("Both the normal and delayed results are from validation. Held-out data does not influence the winner.",
                  "正常与延迟情景均使用验证期数据。留出测试数据不参与选择获胜模型。")}</p>
              </div>}
              {chosen.score_breakdown&&<details open className="ur-score-details">
                <summary>{bilingual("Why this score? Validation-only breakdown","评分依据：仅验证期的分项得分")}</summary>
                <p>{bilingual("These are ranking points, not expected returns. Negative points are penalties. Held-out results never enter the ranking.",
                  "这些数字是排名分值，而非预期收益。负数表示扣分，留出测试期收益不参与排名。")}</p>
                <div className="ur-scroll"><table><thead><tr><th>{bilingual("Component","评分项")}</th><th>{bilingual("Points","分值")}</th></tr></thead>
                  <tbody>{Object.entries(chosen.score_breakdown.components).map(([key,value])=><tr key={key}>
                    <td>{label(key.replace(/_points$/,""))}</td><td>{value.toFixed(2)}</td></tr>)}</tbody>
                  <tfoot><tr><th>{bilingual("Total score","综合得分")}</th>
                    <th>{chosen.score_breakdown.total.toFixed(2)}</th></tr></tfoot></table></div>
              </details>}
              {chosen.held_out_cost_audit&&<details className="ur-score-details">
                <summary>{bilingual("Execution cost attribution, USD","执行成本分项（美元）")}</summary>
                <div className="ur-kpis">
                  {[
                    [bilingual("Explicit fees and financing","显性费用与融资"),chosen.held_out_cost_audit.explicit_total_usd],
                    [bilingual("Commission and FX","佣金及换汇"),chosen.held_out_cost_audit.transaction_and_fx_usd],
                    [bilingual("Margin interest","融资利息"),chosen.held_out_cost_audit.margin_interest_usd],
                    [bilingual("Short borrow","融券借贷"),chosen.held_out_cost_audit.short_borrow_usd],
                    [bilingual("Estimated spread","估算买卖价差"),chosen.held_out_cost_audit.estimated_spread_usd],
                    [bilingual("Estimated slippage","估算滑点"),chosen.held_out_cost_audit.estimated_slippage_usd],
                  ].map(([key,value])=><div key={String(key)}><small>{key}</small><strong>{"$"+Number(value).toFixed(2)}</strong></div>)}
                </div><p>{bilingual("Spread and slippage are already embedded in fill prices. Do not add them to explicit charges as a second deduction.",
                  "买卖价差和滑点已计入模拟成交价，不应重复作为显性成本扣除。")}</p>
              </details>}
              {chosen.model==="blended_portfolio"&&<p className="ur-warning">{bilingual(
                "Blends support saved private versions and date-scoped or walk-forward research, but not interactive replay or live monitoring.",
                "混合策略支持私人版本以及按日期或滚动验证研究，但不支持交互式回放或实时监控。")}</p>}
              {selectedSpec&&<TournamentStrategyInspector key={`${active.id}-${chosen.rank}`} spec={selectedSpec}
                researchStudy={researchJob?.selection===selectedKey?researchJob.job:null} costs={{
                commission_usd:Number(result.execution_assumptions.commission_usd),
                slippage_bps:Number(result.execution_assumptions.slippage_bps),
                fx_conversion_bps:Number(result.execution_assumptions.fx_conversion_bps),
                base_currency:String(result.execution_assumptions.base_currency),
              }} />}
              <p>{t(chosen.research_only?"Synthetic research model":"Executable allocation model")}: {label(chosen.model)} · {active?.params.max_position_pct}% {t("Maximum position weight (%)")} ·
                {t("Every 21 common sessions")} · {active?.params.delay_sessions} {t("session execution delay")}</p>
              <div className="ur-actions">
                {chosen.research_only?
                  <button type="button" className="ur-primary" disabled={busy}
                    aria-busy={busy&&promotionTarget==="research"}
                    onClick={()=>void promote("research")}>
                    {busy&&promotionTarget==="research"?t("Starting historical study..."):
                      t("Run this strategy in historical research")}
                  </button>:
                  <button type="button" className="ur-primary" disabled={busy}
                    aria-busy={busy&&promotionTarget==="simulation"}
                    onClick={()=>void promote("simulation")}>
                    {busy&&promotionTarget==="simulation"?t("Preparing historical replay..."):
                      t("Load this strategy into simulation")}
                  </button>}
                <button type="button" className="ur-secondary"
                  disabled={busy||chosen.research_only||chosen.restricted_research||chosen.short_proxy_research||customResearchExposure}
                  aria-busy={busy&&promotionTarget==="live"}
                  onClick={()=>void promote("live")}>
                  {chosen.research_only?t("Live engine unavailable for short or margin models"):
                    customResearchExposure?t("Live engine unavailable for custom research exposure"):
                    (chosen.restricted_research||chosen.short_proxy_research)?
                      t("Live engine unavailable for restricted ETFs"):
                    (busy&&promotionTarget==="live")?t("Opening Live Engine..."):
                      t("Open in Live Engine (paper first)")}
                </button>
              </div>
              <p>{chosen.model==="blended_portfolio"?
                bilingual("Shared-cash blends now support private saved versions, historical period studies and walk-forward revalidation. Live execution remains disabled.","共享现金混合策略现已支持私人策略版本、历史区间研究和滚动验证。实时执行仍然禁用。"):
                chosen.research_only?
                t("Short and margin strategies can run in the historical signed-position research engine. Click Run this strategy in historical research to see simulated fills, equity changes and risk. Cash-only replay and live broker monitoring do not support these exposures."):
                customResearchExposure?
                  t("Custom investment and equity caps are preserved when saving and replaying this long-only strategy. Live monitoring is disabled until it can reproduce those research exposure rules."):
                  t("Supported cash-funded models can be loaded into simulation and paper monitoring. Leveraged and inverse ETFs are separately restricted for live monitoring.")}</p>
              {result.research_objective==="high_performance"&&chosen.validation_objectives&&<div className="ur-objective-results">
                <h4>{t("Return and risk objectives")}</h4>
                <div className="ur-kpis">
                  <div><small>{t("Validation CAGR")}</small>
                    <strong>{pct(chosen.validation_objectives.cagr_pct??NaN)}</strong></div>
                  <div><small>{t("Validation excess Sharpe")}</small>
                    <strong>{chosen.validation_objectives.excess_sharpe?.toFixed(2)??"N/A"}</strong></div>
                  <div><small>{t("Held-out CAGR")}</small>
                    <strong>{pct(chosen.held_out_objectives?.cagr_pct??NaN)}</strong></div>
                  <div><small>{t("Held-out excess Sharpe")}</small>
                    <strong>{chosen.held_out_objectives?.excess_sharpe?.toFixed(2)??"N/A"}</strong></div>
                  <div><small>{t("Held-out annualized volatility")}</small>
                    <strong>{pct(chosen.held_out_objectives?.annualized_volatility_pct??NaN)}</strong></div>
                  <div><small>{t("Validation Pareto frontier")}</small>
                    <strong>{chosen.pareto_optimal_validation?t("Yes"):t("No")}</strong></div>
                  <div><small>{t("Held-out target reached")}</small>
                    <strong>{!chosen.held_out_target_evaluable?t("Insufficient sessions"):
                      chosen.held_out_target_observed?t("Observed"):t("No")}</strong></div>
                </div>
                {chosen.validation_stability&&<>
                  <h4>{t("Validation subperiod stability")}</h4>
                  <p>{chosen.validation_stability.positive_windows} / {chosen.validation_stability.window_count} {t("positive subperiods")}.
                    {" "}{t("These are sequential diagnostics from one validation run, not independently retrained walk-forward models.")}</p>
                  <div className="ur-scroll"><table><thead><tr>
                    <th>{t("From")}</th><th>{t("To")}</th>
                    <th>{t("Sessions")}</th><th>{t("Return")}</th>
                    <th>{t("Annualized CAGR")}</th><th>{t("Excess Sharpe")}</th>
                  </tr></thead><tbody>{chosen.validation_stability.windows.map((part,i)=><tr key={i}>
                    <td>{new Date(part.start*1000).toLocaleDateString()}</td>
                    <td>{new Date(part.end*1000).toLocaleDateString()}</td>
                    <td>{part.sessions}</td><td>{pct(part.return_pct)}</td>
                    <td>{pct(part.cagr_pct??NaN)}</td>
                    <td>{part.excess_sharpe?.toFixed(2)??"N/A"}</td>
                  </tr>)}</tbody></table></div>
                </>}
              </div>}
              <div className="ur-kpis">
                {[[t("Training return"),pct(chosen.training.return_pct)],
                  [t("Validation return"),pct(chosen.validation.return_pct)],
                  [t("Held-out return"),pct(chosen.held_out.return_pct)],
                  [t("Held-out drawdown"),pct(chosen.held_out.max_drawdown_pct)],
                  [t("Slower fill stress"),pct(chosen.delayed_execution_stress.return_pct)],
                  [t("Simulated costs"),chosen.held_out.fees.toFixed(2)],
                  [t("Validation Sharpe (zero cash rate)"),chosen.validation.sharpe?.toFixed(2)??"N/A"],
                  [t("Validation Sortino"),chosen.validation.sortino?.toFixed(2)??"N/A"],
                  [t("Peak gross leverage"),chosen.held_out.peak_gross_leverage?.toFixed(2)??"N/A"],
                  [t("Margin interest"),chosen.held_out.margin_interest?.toFixed(2)??"N/A"],
                  [t("Short borrow costs"),chosen.held_out.short_borrow_cost?.toFixed(2)??"N/A"],
                  [t("Margin calls"),chosen.held_out.margin_calls??0]].map(([name,value])=>
                  <div key={name}><small>{name}</small><strong>{value}</strong></div>)}
              </div>
              {(chosen.restricted_research||chosen.short_proxy_research)&&
                <p className="ur-warning">{t("Leveraged/inverse ETF exposure is research-only, not a share short or approved broker order.")}</p>}
              {chosen.coverage&&<p>{t("Actual common history")}: {chosen.coverage.first_session}
                {" → "}{chosen.coverage.last_session} · {chosen.coverage.common_sessions} {t("common sessions")}.</p>}
              {chosen.validation_regimes&&<details open><summary>{t("Historical validation performance by market regime")}</summary>
                <div className="ur-scroll"><table><thead><tr>
                  <th>{t("Regime")}</th><th>{t("Observed sessions")}</th>
                  <th>{t("Compounded return")}</th><th>{t("Positive days")}</th><th>{t("Worst day")}</th>
                </tr></thead><tbody>{Object.entries(chosen.validation_regimes.regimes).map(([regime,x])=>
                  <tr key={regime}><td>{label(regime)}</td><td>{x.observations}</td>
                    <td>{pct(x.return_pct)}</td><td>{pct(x.positive_day_pct)}</td><td>{pct(x.worst_day_pct)}</td></tr>)}
                </tbody></table></div></details>}
              {(chosen.held_out_execution_sample?.length??0)>0&&<details>
                <summary>{t("Historical test trade executions")}</summary>
                <div className="ur-scroll"><table><thead><tr><th>{t("Time")}</th><th>{t("Asset")}</th>
                  <th>{t("Side")}</th><th>{t("Quantity")}</th><th>{t("Price")}</th><th>{t("Fee")}</th></tr>
                </thead><tbody>{chosen.held_out_execution_sample?.map((x,i)=><tr key={i}>
                  <td>{new Date(x.time*1000).toLocaleDateString()}</td>
                  <td>{x.symbol.toUpperCase()}</td><td>{label(x.side)}</td><td>{x.quantity}</td>
                  <td>{x.price.toFixed(2)}</td><td>{x.fee.toFixed(2)}</td></tr>)}</tbody></table></div>
              </details>}
              <p>{chosen.execution_model}</p>
              {chosen.scenario_calibration&&<p>{chosen.scenario_calibration}</p>}
              <h4>{t("Hypothetical 10-120 session scenarios")}</h4>
              <div className="ur-scroll"><table><thead><tr><th>{t("Scenario")}</th>
                <th>{t("Sessions")}</th><th>5%</th><th>{t("Median")}</th><th>95%</th><th>{t("Median drawdown")}</th>
              </tr></thead><tbody>{chosen.hypothetical_scenarios.paths.map(row=><tr key={`${row.name}-${row.horizon_sessions}`}>
                <td>{label(row.name)}</td><td>{row.horizon_sessions}</td><td>{pct(row.p05_return_pct)}</td><td>{pct(row.median_return_pct)}</td>
                <td>{pct(row.p95_return_pct)}</td><td>{pct(row.median_max_drawdown_pct)}</td>
              </tr>)}</tbody></table></div>
              <h4>{t("Daily scenario trajectory")}</h4>
              {chosen.hypothetical_scenarios.paths.filter(x=>x.daily?.length).map(path=>
                <details key={`${path.name}-${path.horizon_sessions}`}><summary>{label(path.name)} · {path.horizon_sessions} {t("Sessions")} · {t("Day-by-day percentile bands")}</summary>
                  <div className="ur-scroll"><table><thead><tr>
                    <th>{t("Trading session")}</th><th>{t("Downside 5%")}</th>
                    <th>{t("Median")}</th><th>{t("Upside 95%")}</th>
                  </tr></thead><tbody>
                    {(path.daily??[]).map(point=><tr key={point.session}>
                      <td>{point.session}</td><td>{pct(point.p05_return_pct)}</td>
                      <td>{pct(point.median_return_pct)}</td><td>{pct(point.p95_return_pct)}</td>
                    </tr>)}
                  </tbody></table></div>
                </details>)}
              <p>{t("Scenario paths are hypothetical resamples, not forecasts or calibrated probabilities.")}</p>
            </article>}
            <details><summary>{t("Cost model and limitations")}</summary>
              <p>{result.selection_method}</p>
              <p>{t("FX conversion assumption")}: {Number(result.execution_assumptions.fx_conversion_bps)/100}% ·
                {t("Slippage")}: {result.execution_assumptions.slippage_bps} bps ·
                {t("Commission")}: {result.execution_assumptions.commission_usd} USD</p>
              <p>{result.excluded_count} {t("excluded symbols")}</p>
              {result.limitations.map((line,i)=><p key={i}>{line}</p>)}
            </details>
          </>}
        </>}
      </section>
    </div>
  </main>;
}
