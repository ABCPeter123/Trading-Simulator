import {useI18n} from "./i18n";
import CustomStrategyAnalysis from "./CustomStrategyAnalysis";
import type {CustomPeriodJob} from "./tournamentApi";
import {MODEL_EXPLANATIONS,explanationText} from "./strategyNarratives";
import "./tournamentInspector.css";

export interface TournamentModelSpec {
  version:1|2; model:string; symbols:string[];
  max_position_pct:number; delay_sessions:1|2; rebalance_sessions:number;
  restricted_research?:boolean; short_proxy_research?:boolean; research_only?:boolean;
  target_investment_pct?:number;equity_class_cap_pct?:number;
  redistribute_excess?:boolean;
}

type ResearchCosts = {
  commission_usd?:number; slippage_bps?:number;
  fx_conversion_bps?:number; base_currency?:string;
};

const DEFAULT_CAPS=[
  ["Equities","股票","70%"],["Bonds","债券","55%"],
  ["Commodities","商品","35%"],["Real estate","房地产","20%"],
  ["Crypto-classified","加密资产类别","10%"],
] as const;
const RISK_PARITY_CAPS=[
  ["Equities","股票","45%"],["Bonds","债券","30%"],
  ["Commodities","商品","20%"],["Real estate","房地产","12%"],
  ["Crypto-classified","加密资产类别","5%"],
] as const;
const EQUITY_HEDGE_CAPS=[
  ["Equities","股票","50%"],["Bonds","债券","30%"],["Commodities","商品","20%"],
] as const;
const CASH_MODELS=new Set([
  "equal_weight","inverse_volatility","trend_filter",
  "relative_momentum","volatility_target",
]);
const RESEARCH_ONLY_MODELS=new Set(["leveraged_trend","long_short_momentum","market_neutral"]);

export default function TournamentStrategyInspector({
  spec,costs,context="research",researchStudy=null,
}:{
  spec:TournamentModelSpec;exactCode?:string;costs?:ResearchCosts;
  researchStudy?:CustomPeriodJob|null;
  context?:"research"|"simulation"|"live";
}){
  const {locale}=useI18n();
  const l=(en:string,zh:string)=>locale==="zh-CN"?zh:en;
  const narrative=MODEL_EXPLANATIONS[spec.model];
  const caps=CASH_MODELS.has(spec.model)?
    DEFAULT_CAPS.map(([en,zh,value])=>
      [en,zh,en==="Equities"&&spec.equity_class_cap_pct!=null?
        spec.equity_class_cap_pct+"%":value] as const):
    spec.model==="diversified_risk_parity"?RISK_PARITY_CAPS:
    spec.model==="equity_hedge"?EQUITY_HEDGE_CAPS:null;
  const researchOnly=Boolean(spec.research_only||RESEARCH_ONLY_MODELS.has(spec.model));
  return <section className="tsi" aria-label={l("Detailed strategy explanation","详细策略说明")}>
    <header className="tsi-header">
      <div>
        <h4>{narrative ? explanationText(narrative.name,locale) : l("Detailed strategy breakdown","详细策略拆解")}</h4>
        <p>{narrative
          ?explanationText(narrative.goal,locale)
          :l("This model has no verified written explanation yet.","此模型暂时没有经核实的文字说明。")}</p>
      </div>
      <span className="tsi-mode">{context==="research"?l("Historical research","历史研究"):
        context==="simulation"?l("Historical replay","历史回放"):l("Live monitoring","实时监控")}</span>
    </header>

    {(spec.target_investment_pct!==undefined||spec.equity_class_cap_pct!==undefined)&&
      <p className="tsi-intro">{l("This research version uses custom investment targets:","此研究版本使用自定义投资目标：")}
        {" "}{l("invested capital","已投资资金")} {spec.target_investment_pct??95}%,
        {" "}{l("equity category cap","股票类别上限")} {spec.equity_class_cap_pct??70}%,
        {" "}{spec.redistribute_excess?
          l("unused eligible allocation is redistributed.","未分配的合格仓位将重新配置。"):
          l("unused allocation remains as cash.","未分配的资金保留为现金。")}
      </p>}
    <div className="tsi-fields">
      <div><small>{l("Portfolio basket","资产组合")}</small><strong>{spec.symbols.map(s=>s.toUpperCase()).join(" · ")}</strong></div>
      <div><small>{l("Maximum per asset","单项资产仓位上限")}</small><strong>{spec.max_position_pct}%</strong></div>
      <div><small>{l("Rebalance frequency","再平衡频率")}</small><strong>{l("Every ","每 ")}{spec.rebalance_sessions} {l("shared trading sessions","个共同交易日")}</strong></div>
      <div><small>{l("Historical execution delay","历史执行延迟")}</small><strong>{spec.delay_sessions===1?l("Next session's open","下一交易日开盘"):l("One extra session of signal lag","信号额外滞后一个交易日")}</strong></div>
    </div>

    {researchOnly&&<div className="tsi-notice" role="note">
      <strong>{l("Historical research only","仅限历史研究")}</strong>
      <p>{l("This strategy can simulate borrowing, shorting or margin. It cannot be deployed to the current cash-only live engine or executed through Wealthsimple by the simulator.",
        "本策略可能模拟借贷、卖空或保证金。当前仅支持现金账户的实时引擎不能部署此策略，模拟器也不会通过 Wealthsimple 自动执行。")}</p>
    </div>}
    {(spec.restricted_research||spec.short_proxy_research)&&<div className="tsi-notice" role="note">
      {l("This basket includes leveraged or inverse ETF products. They are research/replay references and are not approved for live monitoring.",
        "此组合包含杠杆或反向ETF，仅供研究和历史回放参考，不允许用于实时监控。")}
    </div>}

    {narrative&&<>
      <h5>{l("1. How this strategy makes decisions","1. 策略如何做出决策")}</h5>
      <p className="tsi-intro">{l("These steps describe the actual model's allocation rules. They are not generated from its historical performance or an AI forecast.",
        "以下步骤说明模型实际使用的资产配置规则，并非依据历史收益表现或AI预测生成。")}</p>
      <ol className="tsi-stages">
        {narrative.steps.map((step,i)=><li key={i}>
          <div className="tsi-step-number" aria-hidden="true">{i+1}</div>
          <div className="tsi-step-body">
            <h6>{explanationText(step.title,locale)}</h6>
            <p>{explanationText(step.detail,locale)}</p>
          </div>
        </li>)}
      </ol>

      <h5>{l("2. Exposure and risk limits","2. 敞口与风险限制")}</h5>
      <div className="tsi-explainer">
        <p>{l("The position limit applies to every asset individually. Category ceilings apply to the aggregate allocation of all assets in that class. If a cap reduces a position, the excess stays in cash rather than being redistributed.",
          "单项仓位上限适用于每项资产。类别上限适用于该类别所有资产的总配置。若限制削减某项仓位，超出部分会保留为现金，而不会重新分配。")}</p>
        {caps&&<div className="tsi-limits" aria-label={l("Category exposure limits","资产类别敞口限制")}>
          {caps.map(([en,zh,value])=><div key={en}><span>{l(en,zh)}</span><strong>{value}</strong></div>)}
        </div>}
        {spec.model==="defensive_rotation"&&<p>{l("Category limits change with the market regime: in risk-on periods, equities are capped at 65%; in risk-off periods, bonds are capped at 55% and commodities at 35%.",
          "类别上限随市场环境变化：风险偏好阶段股票最多65%；风险规避阶段债券最多55%、商品最多35%。")}</p>}
        {!caps&&spec.model!=="defensive_rotation"&&<p>{l("This advanced model uses its own long/short or leveraged exposure budgets, together with the per-asset position cap. The standard long-only asset-class ceilings are not automatically applied.",
          "此高级模型使用独立的多空或杠杆敞口预算，并结合单项仓位上限；标准多头类别上限不会自动适用。")}</p>}
        {spec.model==="equity_hedge"&&<p>{l("The three listed category caps apply to equities, bonds and commodities; this model does not impose separate category caps on other recognized groups.",
          "上述三项类别上限仅适用于股票、债券和商品；该模型未对其他已识别资产类别单独设置类别上限。")}</p>}
        <p className="tsi-caveat"><strong>{l("Important trade-off:","重要权衡：")}</strong> {explanationText(narrative.caveat,locale)}</p>
      </div>

      <h5>{l("3. What happens during a historical backtest","3. 历史回测的具体过程")}</h5>
      <ol className="tsi-rules">
        <li>{l("The engine aligns real daily price observations across every basket member. Days without a matching observation are excluded; missing prices are not fabricated. It requires enough history to warm up all indicators.",
          "引擎对齐组合中所有资产的真实日价格数据，排除没有共同记录的交易日，不会编造缺失价格；还须有足够历史用于指标预热。")}</li>
        <li>{l("The strategy sees only earlier completed closing prices, never the current fill session's close. Each rebalance uses the selected historical delay: the normal case reads data through the prior close; the two-session case uses one additional close of lag.",
          "策略只能看到此前已完成的收盘价，不能看到当前成交交易日的收盘价。普通延迟使用上一交易日之前的信息；两交易日延迟则额外滞后一个收盘数据。")}</li>
        <li>{l("At the scheduled rebalance, the allocation function calculates a target percentage for every asset. The engine estimates portfolio equity at the recorded opening prices, calculates target shares, sells excess holdings first, then buys subject to cash, position limits and costs.",
          "到达再平衡时点后，配置函数为每项资产计算目标比例。引擎以历史开盘价估计账户权益和目标股数，先卖出超额仓位，再按现金、仓位与费用约束进行买入。")}</li>
        <li>{researchOnly
          ?l("The advanced research ledger permits negative share positions and borrowed funding. It charges daily modeled short-borrow fees and interest on negative cash and monitors the maintenance-margin threshold.",
            "高级研究账本允许负股数和借款，按日计提模拟借券费及负现金融资利息，并监控维持保证金门槛。")
          :l("The long-only research ledger cannot spend more cash than it has. Equity and ETF quantities are rounded down to whole shares, and the simulator records trade prices, fees, quantities and timestamps.",
            "多头研究账本不能超支。股票和ETF股数向下取整到整数股，模拟器记录成交价格、费用、数量和时间戳。")}</li>
        <li>{l("After each trading session, positions are valued using that session's actual historical closing prices. The resulting equity curve is used to calculate returns, drawdowns, volatility, turnover, trade counts and financing costs where relevant.",
          "每个交易日结束后，按当日真实历史收盘价对持仓估值。引擎据此生成净值曲线，计算收益、回撤、波动率、换手率、成交次数及相关融资费用。")}</li>
      </ol>

      <h5>{l("4. How the tournament judges this strategy","4. 策略竞赛如何评分")}</h5>
      <div className="tsi-explainer">
        <p>{l("Each historical basket is divided chronologically into 60% training, 20% validation and a final 20% held-out test. Training and validation are simulated independently, starting with the same $100,000 virtual capital in each segment.",
          "每个历史资产篮子按时间顺序划分为60%训练、20%验证和最后20%留出测试。训练与验证分别独立模拟，且每个区间均以10万美元虚拟本金开始。")}</p>
        <p>{l("Validation performance determines the shortlist. The score rewards validation return and subtracts penalties for maximum drawdown, turnover, volatility, losses in the worst observed market regime, and very few trades. Candidates exceeding the chosen drawdown limit or failing trading and exposure checks are excluded.",
          "候选名单依据验证期表现决定。评分以验证收益为基础，扣除最大回撤、换手率、波动率、最差已观察市场阶段亏损及交易次数过少的惩罚。超过设置回撤限制或不满足交易及敞口要求的候选会被排除。")}</p>
        <p>{l("The final shortlist includes representatives of different model families, so it is not simply the ten highest raw scores. Only after selection does the system run the held-out test and a slower, higher-slippage execution stress test. Hypothetical future scenarios resample historical outcomes and are not price predictions.",
          "最终候选名单兼顾不同策略家族，并非只取原始评分最高的十项。选定后才执行留出测试，以及额外延迟且滑点更高的执行压力测试。假设未来情景根据历史结果重采样，不属于价格预测。")}</p>
      </div>

      <h5>{l("5. Execution assumptions and practical limits","5. 执行假设及实际限制")}</h5>
      <div className="tsi-explainer">
        <p>{l("The research backtester models orders at a subsequent shared session's historical opening price, adjusted for assumed bid-ask spread and slippage. These are modeled fills, not actual exchange transactions or broker quotes.",
          "研究回测按后续共同交易日的历史开盘价模拟成交，并按假设买卖价差和滑点调整。这些只是模拟成交，不是真实交易所订单或券商报价。")}</p>
        {costs&&<div className="tsi-limits">
          <div><span>{l("Slippage assumption","滑点假设")}</span><strong>{costs.slippage_bps??l("Not reported","未提供")} {l("basis points","基点")}</strong></div>
          <div><span>{l("Commission per modeled order","每笔模拟订单佣金")}</span><strong>{costs.commission_usd??l("Not reported","未提供")} USD</strong></div>
          <div><span>{l("Cross-currency conversion cost","跨币种转换费用")}</span><strong>{costs.fx_conversion_bps??l("Not reported","未提供")} {l("basis points","基点")}</strong></div>
          <div><span>{l("Account base currency","账户基准货币")}</span><strong>{costs.base_currency??"USD"}</strong></div>
        </div>}
        {context==="research"&&<p>{l("Historical research does not automatically activate this strategy. The portfolio can be imported into replay only where its exposures are supported.",
          "历史研究不会自动启用该策略。只有敞口类型受到支持时，才可将组合导入历史回放。")}</p>}
        {context==="simulation"&&<p>{l("Historical replay uses the same allocation rules, but its order-fill and fee implementation differs from tournament research. The two equity curves therefore may not match exactly. Cash-only replay cannot open short positions.",
          "历史回放沿用相同的资产配置规则，但订单成交和费用实现与策略竞赛不同，因此两者净值曲线可能不完全一致。现金账户回放不能建立空头。")}</p>}
        {context==="live"&&<p>{l("Live monitoring uses completed market candles to generate suggested target-share changes. It reads confirmed trade-journal holdings, not broker account balances, and never sends a brokerage order. Tournament portfolio monitoring is daily only.",
          "实时监控根据已完成行情计算建议的目标股数变化，读取已确认的交易日志持仓而非券商账户余额，也不会自动下单。竞赛投资组合仅支持日线监控。")}</p>}
        <p>{l("These results do not include a complete real-world model of taxes, dividends, corporate actions, changing borrow availability, market impact or broker execution. Historical success does not establish future profitability.",
          "这些结果未完整建模税费、分红、公司行为、借券可得性变化、市场冲击或真实券商成交。历史表现不保证未来盈利。")}</p>
      </div>
    </>}
    <div id="ur-custom-study"><CustomStrategyAnalysis spec={spec} initialJob={researchStudy}/></div>
  </section>;
}
