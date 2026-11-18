/** Human-facing explanations of the versioned tournament model families.
 * These describe the generic public engine, never an owner's private outcomes.
 * Keep in sync with portfolio_research._weights and advanced_portfolio_research.weights.
 */
export type LocalizedExplanation = readonly [english:string, chinese:string];
export type ExplanationStep = {title:LocalizedExplanation; detail:LocalizedExplanation};
export interface ModelExplanation {
  goal:LocalizedExplanation;
  steps:ExplanationStep[];
  caveat:LocalizedExplanation;
}
const b=(en:string,zh:string):LocalizedExplanation=>[en,zh];
const s=(enTitle:string,zhTitle:string,enDetail:string,zhDetail:string):ExplanationStep=>({
  title:b(enTitle,zhTitle),detail:b(enDetail,zhDetail),
});
export const explanationText=(value:LocalizedExplanation,locale:"en"|"zh-CN")=>
  value[locale==="zh-CN"?1:0];

export const MODEL_EXPLANATIONS:Record<string,ModelExplanation>={
  equal_weight:{
    goal:b("Spread a long-only allocation across every asset in the selected basket, without forecasting returns or preferring lower-risk assets.","在选定资产篮子中等权配置多头，不预测收益，也不优先选择低波动资产。"),
    steps:[
      s("Eligible assets","参与资产","Every instrument in the chosen basket receives an identical initial score. Price momentum, volatility and market regime do not affect selection.","篮子中的每个品种获得相同的初始评分。动量、波动率和市场环境均不影响选取。"),
      s("Initial allocation","初始配置","Divide a maximum 95% invested budget equally across the basket. For example, five assets would initially receive 19% each before limits.","将最多95%的资金平均分配给所有资产。例如，五项资产在应用限制前各占19%。"),
      s("Position limits","仓位限制","Reduce any asset exceeding the configured single-position cap. Then proportionally reduce any asset class exceeding its standard class cap. Excess is left in cash, not reassigned.","先将超过单项仓位上限的配置削减，再按比例降低超过标准类别上限的仓位。剩余资金保留为现金，不再分配。"),
      s("Rebalance behavior","再平衡行为","At each scheduled rebalance, compare current holdings with the new equal-weight targets. Sell excess shares, then buy underweight shares, subject to available cash and modeled costs.","在每次定期再平衡时，将现有持仓与新的等权目标比较。先卖出超配股份，再在现金和模拟费用允许的范围内买入低配股份。"),
    ],
    caveat:b("Equal weighting is not equal risk: a volatile asset may contribute much more portfolio risk than a stable one.","等权不等于风险相等。高波动资产可能贡献远高于低波动资产的组合风险。"),
  },
  inverse_volatility:{
    goal:b("Prefer assets with more stable recent daily returns while keeping broad, long-only diversification.","优先配置近期日收益波动较小的资产，同时维持多资产多头分散配置。"),
    steps:[
      s("Measure recent risk","衡量近期风险","Calculate close-to-close returns from up to the previous 60 completed sessions for each asset. Use sample standard deviation as daily volatility, with a minimum of 0.2%.","计算各资产最近最多60个已完成交易日的收盘收益率，采用样本标准差衡量日波动率，最低按0.2%计。"),
      s("Determine relative weights","确定相对权重","Give each asset an initial score equal to one divided by its volatility. An asset with 1% daily volatility receives twice the score of one with 2% volatility.","每个资产的初始评分等于其波动率的倒数。日波动率为1%的资产得到日波动率为2%资产的两倍评分。"),
      s("Set portfolio exposure","设置组合敞口","Normalize the scores toward a total investment budget of 95%. Apply the individual position cap and standard asset-class limits, leaving any unused amount in cash.","将评分标准化为最多95%的总投资比例，再执行单项仓位及标准类别上限。未分配的资金保留为现金。"),
      s("Recalculate on schedule","定期重新计算","At each rebalance, update the 60-session risk estimates. An asset becoming more volatile generally receives a smaller proposed allocation, all else equal.","每次再平衡重新估计60日风险。其他条件不变时，波动率升高的资产通常会获得更小的目标仓位。"),
    ],
    caveat:b("This is inverse-volatility weighting, not full risk parity. It does not use an asset covariance matrix or explicitly optimize portfolio correlations.","这是波动率倒数加权，并非完整风险平价。该模型不使用资产协方差矩阵，也不直接优化组合相关性。"),
  },
  trend_filter:{
    goal:b("Hold only assets trading above their medium-term trend, then give relatively more weight to the less volatile qualifying assets.","只持有价格高于中期趋势线的资产，并对其中波动率较低的资产给予相对更高权重。"),
    steps:[
      s("Identify the trend","判断趋势","For each asset, average its previous 126 completed daily closes. Compare the latest completed close with that average.","计算每项资产之前126个已完成交易日的收盘价均值，并与最新已完成的收盘价比较。"),
      s("Accept or exclude","纳入或排除","An asset qualifies only when its latest close is strictly above its 126-session average. Assets at or below that average receive a zero allocation.","仅当最新收盘价严格高于126日均线时，该资产才符合条件。等于或低于均线的资产配置为零。"),
      s("Size eligible assets","分配合格资产仓位","Estimate 60-session daily volatility for qualifying assets. Assign larger raw weights to less volatile assets, targeting no more than 95% total exposure before position and class caps.","对符合条件的资产估计60日波动率，波动率越低原始权重越高。应用仓位及类别上限之前，总目标敞口不超过95%。"),
      s("Move to cash if necessary","必要时转为现金","If no assets meet the trend condition, the strategy targets 100% cash. It does not automatically short downtrending assets or buy a defensive hedge.","如果没有资产符合趋势条件，策略目标变为100%现金；不会自动做空下跌资产或购买防御性对冲工具。"),
    ],
    caveat:b("The moving average can react slowly after abrupt market reversals. It is a retrospective filter, not a prediction.","均线对市场突然反转可能反应较慢。它是历史趋势过滤条件，而非未来预测。"),
  },
  relative_momentum:{
    goal:b("Concentrate long exposure in the strongest recently performing assets, provided their combined recent momentum is positive.","将多头资金集中在近期表现最强且综合动量为正的资产上。"),
    steps:[
      s("Calculate momentum","计算动量","For each asset, compute the price change from the close 64 sessions back to the latest completed close, and separately from 127 sessions back. Give each change 50% of the total score.","计算各资产最新已完成收盘价相对64个及127个交易时段之前的涨跌幅，两项各占综合评分的50%。"),
      s("Rank the basket","对资产排序","Sort assets by their combined momentum score. Keep the top one third rounded up, but never fewer than two candidates. Ties follow the engine's deterministic order.","按综合动量评分排序，保留排名前约三分之一并向上取整，候选数至少为两项。同分时遵循引擎的确定性排序。"),
      s("Require positive momentum","要求正动量","Only top-ranked candidates with a strictly positive score receive an allocation. All lower-ranked or nonpositive-scoring assets have zero target weight.","仅对排名靠前且评分严格为正的资产进行配置。排名较低或评分非正的资产目标权重为零。"),
      s("Size and limit exposure","计算与限制仓位","Among qualifying assets, allocate inversely to 60-session volatility. Limit gross investment to 95% before individual and standard asset-class caps; keep any remainder in cash.","在合格资产间按60日波动率倒数分配权重。单项和标准类别上限应用前总投资不超过95%，剩余资金保留为现金。"),
    ],
    caveat:b("This follows past winners and can suffer sharp reversals. It does not require the selected assets to be diversified across industries.","该方法追逐过去的强势资产，可能受到快速趋势反转影响，也不要求被选资产来自不同产业。"),
  },
  volatility_target:{
    goal:b("Keep a long-only, inverse-volatility portfolio while cutting investment exposure when recent estimated portfolio volatility is high.","维持波动率倒数加权的多头组合，在近期估计组合波动率偏高时降低投资比例。"),
    steps:[
      s("Build initial proportions","建立初始比例","Estimate each asset's daily volatility from up to 60 completed returns, with a 0.2% floor. Give each asset an initial weight proportional to the inverse of its volatility.","从最多60个已完成日收益率估计每项资产的波动率，最低计为0.2%。根据波动率倒数计算初始权重。"),
      s("Estimate combined risk","估算整体风险","Combine the weighted daily returns from the same recent window into a hypothetical portfolio return series. Multiply its daily standard deviation by the square root of 252 to annualize it.","按初始权重合成同一时间窗口内的每日组合收益序列，并以日标准差乘以252的平方根估算年化波动率。"),
      s("Target annual volatility","设定年化波动率目标","Start with a 95% maximum invested budget. If estimated annual volatility exceeds the 12% target, reduce invested exposure in proportion to 12% divided by estimated volatility. Never scale above 95%.","总投资预算最初上限为95%。若估计年化波动率超过12%的目标，则按12%除以估计波动率的比例减少投资敞口，绝不提高到95%以上。"),
      s("Apply concentration controls","应用集中度限制","Apply the configured per-asset maximum and standard class caps after scaling. Money removed by either volatility scaling or caps stays in cash.","按波动率缩放之后执行单项和标准类别上限。缩放或仓位上限释放出的资金保留为现金。"),
    ],
    caveat:b("The 12% figure is a target based on past price changes, not a volatility guarantee. Sudden losses and overnight gaps can exceed the estimate.","12%是依据历史价格变化估计的目标，而非波动率保证。突发亏损和隔夜跳空可能超出估计。"),
  },
  defensive_rotation:{
    goal:b("Switch between equity exposure and actual bond or commodity holdings according to the breadth of equity trends.","根据股票整体趋势强弱，在股票与实际债券或商品资产之间切换。"),
    steps:[
      s("Require mixed assets","要求混合资产","The basket must contain at least one equity and at least one defensive bond or commodity instrument. If either side is missing, this candidate cannot be evaluated.","资产篮子必须同时包含至少一项股票和一项债券或商品等防御资产。若缺少其中一类，该候选策略无法评估。"),
      s("Vote on the market regime","判断市场环境","For each equity, check whether its latest completed close exceeds its 126-session moving average. The regime is risk-on when at least half of equities meet that condition, rounded up for odd counts.","逐一检查股票最新已完成的收盘价是否高于126日均线。若达到至少一半股票符合条件（奇数数量向上取整），则判断为风险偏好阶段。"),
      s("Risk-on behavior","风险偏好时的操作","When the regime is risk-on, allocate across all equities using inverse 60-session volatility, not only the equities individually above their averages. Limit equity exposure to 65%, even though the nominal gross budget is 95%.","在风险偏好阶段，对所有股票按60日波动率倒数配置，并非只选择站上均线的股票。虽然名义总预算为95%，但股票敞口上限为65%。"),
      s("Risk-off behavior","风险规避时的操作","Otherwise, invest across available bonds and commodities by inverse volatility. Bond exposure is capped at 55% and commodity exposure at 35%. No equities are selected in this regime.","否则，对可用债券和商品资产按波动率倒数配置。债券敞口上限为55%，商品敞口上限为35%，该阶段不配置股票。"),
      s("Control each position","限制每项仓位","Apply the configured position cap in either regime. Unused weight remains in cash; the strategy does not use inverse ETFs, options, or short selling as a hedge.","无论哪种环境都应用指定单项仓位上限。未配置比例保留为现金；策略不通过反向ETF、期权或卖空进行对冲。"),
    ],
    caveat:b("The switch is based on a simple majority of backward-looking trends. Bonds and commodities may lose value at the same time as stocks.","切换条件只是历史趋势的简单多数投票。债券和商品也可能与股票同时下跌。"),
  },
  diversified_risk_parity:{
    goal:b("Spread a long-only portfolio across available asset classes with inverse-volatility sizing and particularly strict concentration limits.","以波动率倒数权重及较严格的集中度上限，在可用资产类别之间分散多头投资。"),
    steps:[
      s("Check basket composition","检查资产构成","The strategy requires both equity and defensive bond or commodity exposure in the basket; it will not run if either group is absent.","策略要求资产篮子同时包含股票和债券或商品等防御资产，否则无法运行。"),
      s("Compute raw allocations","计算初始权重","Use the previous 60 daily returns to estimate each asset's volatility. Divide each asset's inverse-volatility score by the total, with a maximum initial investment budget of 95%.","利用之前60个日收益率估计各资产波动率，再将波动率倒数评分按总和标准化，最初总投资上限为95%。"),
      s("Set strict class ceilings","施加严格类别上限","Restrict equities to 45%, bonds to 30%, commodities to 20%, real estate to 12%, and crypto-classified holdings to 5%, with an additional individual-position cap.","将股票、债券、商品、房地产和加密资产类的敞口分别限制在45%、30%、20%、12%和5%，并额外执行单项仓位上限。"),
      s("Retain reserve cash","保留现金储备","When an asset or asset class hits its cap, do not redistribute the excess weight. This can leave a substantial cash balance rather than using the full nominal 95%.","资产或类别达到上限时，不将超出部分重新分配。因此可能留下较多现金，而非使用全部名义95%投资额度。"),
    ],
    caveat:b("Despite its name, this is not mathematical risk-parity optimization: it does not solve for equal marginal risk contributions or account for pairwise correlations.","尽管名称为风险平价，这并非数学意义上的风险平价优化。它不会求解相等的边际风险贡献，也不会考虑两两资产相关性。"),
  },
  equity_hedge:{
    goal:b("Balance long equity holdings with long bond and commodity holdings rather than using direct short positions or derivative hedges.","通过同时持有股票、债券和商品多头来分散风险，而非直接做空或使用衍生品对冲。"),
    steps:[
      s("Require defensive exposure","要求防御资产","The basket must contain at least one equity and a bond or commodity instrument. The model does not manufacture a defensive price history.","资产篮子必须至少包含一项股票以及一项债券或商品资产；模型不会凭空生成防御资产价格。"),
      s("Size every asset","分配各资产仓位","Calculate inverse-volatility scores from up to 60 completed daily returns across all assets in the basket. The starting total exposure budget is 90%.","根据篮子中各资产最近最多60个已完成日收益率的波动率倒数计算权重，初始总敞口预算为90%。"),
      s("Balance categories","平衡资产类别","Cap equities at 50%, bonds at 30% and commodities at 20%, in addition to the individual position cap. The model does not condition these allocations on a new market signal.","除单项仓位上限之外，股票、债券、商品的类别上限分别为50%、30%、20%。该模型不依赖新的市场信号来切换配置。"),
      s("Keep spare cash","保留剩余现金","After applying caps, retain any residual as cash. All asset positions remain long; there is no direct market short or options protection.","执行各项上限后，剩余资金保留为现金。所有资产保持多头，不包含直接市场空头或期权保护。"),
    ],
    caveat:b("The word hedge refers to asset-class diversification, not a guaranteed offset to equity losses. Bonds and commodities can correlate with equities during stress.","这里的对冲指资产类别分散，并不保证抵消股票亏损。压力时期债券和商品也可能与股票同向波动。"),
  },
  leveraged_trend:{
    goal:b("Take amplified long exposure to equities that satisfy both a medium-term trend test and a positive momentum test.","对同时满足中期趋势及正动量条件的股票建立放大的多头敞口。"),
    steps:[
      s("Require equities","要求股票资产","The basket must contain at least two equities. Defensive instruments do not enter this model's active allocation.","资产篮子必须至少包含两项股票。防御资产不参与这一模型的实际配置。"),
      s("Find qualifying trends","筛选趋势","An equity qualifies only when its last completed close is above its 126-session moving average AND its equal-weighted 64/127-session momentum score is positive.","股票必须同时满足最新已完成收盘价高于126日均线，以及64日和127日综合动量评分为正，才符合条件。"),
      s("Target amplified exposure","设置放大敞口","Distribute up to 135% gross long equity exposure across qualifying assets, weighted by inverse 60-session volatility. Cap each equity at the lower of the configured position limit and 40%.","对合格股票按60日波动率倒数配置，目标总多头敞口最高为权益的135%。每项股票上限为配置上限与40%中的较小值。"),
      s("Finance the positions","模拟杠杆融资","The research ledger can hold negative cash from borrowed funding. It applies modeled annual financing costs to negative cash and checks maintenance margin during daily valuation.","研究账本允许借款造成负现金，对负现金按模拟年化融资费率计息，并在每日估值时检查维持保证金比例。"),
      s("Respond to margin risk","处理保证金风险","If equity divided by gross exposure falls below 25%, the simulator flags liquidation and attempts to flatten positions at the next rebalance opportunity.","如果账户权益与总敞口的比率跌破25%，模拟器标记强制平仓，并在下一次允许交易的时点尝试清空仓位。"),
    ],
    caveat:b("Research only. The modeled leverage, financing and maintenance rules are simplified and are not an executable Wealthsimple margin account.","仅供研究。模拟杠杆、融资及维持保证金规则经过简化，并不对应可实际执行的Wealthsimple保证金账户。"),
  },
  long_short_momentum:{
    goal:b("Buy the strongest relative-momentum equities and short the weakest, combining long and negative holdings in one research ledger.","买入相对动量最强的股票并做空最弱的股票，在同一研究账本中组合多头和负持仓。"),
    steps:[
      s("Require a broad equity basket","要求足够多的股票","The basket needs at least four equities. Each equity receives a score combining past 64-session and 127-session price changes with equal importance.","资产篮子至少需要四项股票。每项股票的评分由过去64日及127日价格变化各占一半组成。"),
      s("Choose opposing groups","选取相反方向的资产","Sort equities by momentum. Go long the strongest floor(one third of equity count) and short the weakest equivalent group, with at least one on each side. No positive-score condition is required.","按动量排序。做多排名最高的约三分之一（向下取整），做空数量相同的最弱股票，每侧至少一项。不要求动量评分必须为正。"),
      s("Size long and short books","配置多空仓位","Target up to 95% long notional and 45% short notional, each distributed using inverse 60-session volatility. Each leg has a maximum 40% per asset plus the configured cap.","总多头名义敞口最高95%，总空头最高45%，两侧均按60日波动率倒数分配。每项资产同时受40%及配置上限约束。"),
      s("Simulate short selling","模拟股票卖空","A short sale creates negative shares and credits cash with sale proceeds. Daily short borrow charges and financing costs affect account equity. A 25% maintenance-margin floor can trigger liquidation.","卖空使持仓股数为负，并将卖出所得计入现金。每日借券费用和融资成本影响账户权益，25%的维持保证金下限可触发强制平仓。"),
    ],
    caveat:b("Research only. Real borrow availability, hard-to-borrow rates, recalls and actual short execution are not modeled. A weak long group can lose even while the short group also loses.","仅供研究。实际可借股票、难借费率、借券召回和真实卖空成交均未建模。多头和空头两侧也可能同时亏损。"),
  },
  market_neutral:{
    goal:b("Seek approximately balanced long and short notional exposure using equity momentum rankings, while accounting for synthetic borrow and margin costs.","根据股票动量排名建立名义敞口大致相等的多空仓位，并模拟借券及融资成本。"),
    steps:[
      s("Form two ranked groups","形成两组排序资产","Require at least four equities. Rank them by an equal blend of 64-session and 127-session momentum, going long the strongest third and short the weakest third, rounded down with at least one per side.","至少需要四项股票。根据64日和127日各占一半的动量评分排序，做多最强三分之一并做空最弱三分之一，数量向下取整且每侧至少一项。"),
      s("Balance notional targets","平衡名义敞口","Target up to 65% long and 65% short notional. Each side is weighted by inverse 60-session volatility and capped at the lower of 40% or the configured maximum per asset.","多头和空头名义敞口目标各最高65%。每侧按60日波动率倒数加权，单项上限为40%或配置上限中的较小值。"),
      s("Understand net versus gross","区分净敞口与总敞口","Before caps, the nominal net exposure is approximately zero while gross exposure can approach 130%. Individual caps can make actual long and short totals unequal.","施加仓位上限前，名义净敞口接近零，而总敞口可接近130%。单项仓位上限可能导致实际多空总量不相等。"),
      s("Account for funding and stress","计入融资与压力风险","Use the signed-share ledger to charge daily borrow fees on short positions, interest on negative cash, and apply the 25% maintenance-margin liquidation threshold.","使用正负持仓账本，对空头头寸收取每日借券费，对负现金收取利息，并执行25%的维持保证金强制平仓门槛。"),
    ],
    caveat:b("Research only. Approximately dollar-balanced does not mean beta-neutral or market-risk-free. Correlation, sector and factor neutrality are not optimized.","仅供研究。名义金额大致平衡不等于贝塔中性或没有市场风险。模型不优化相关性、行业或因子中性。"),
  },
};
