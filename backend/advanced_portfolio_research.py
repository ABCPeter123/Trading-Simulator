"""Experimental signed-exposure strategy evaluation. Research only; no broker orders.

Supports actual synthetic short-share and margin-ledger positions, using ONLY
completed daily candles for signals and next-available common-session opens
for trades. Never present an artificial short as a Wealthsimple share order.
"""
from __future__ import annotations
import math
from statistics import mean, stdev
from . import portfolio_research as pr
from .research_optimizer import _stats

MODELS=(
    "defensive_rotation", "diversified_risk_parity", "equity_hedge",
    "leveraged_trend", "long_short_momentum", "market_neutral",
)
SHORT_MODELS=frozenset(("long_short_momentum","market_neutral"))
MARGIN_MODELS=frozenset(("leveraged_trend",))
RESEARCH_ONLY=frozenset(SHORT_MODELS | MARGIN_MODELS)
BORROW_RATE_ANNUAL=.06
MARGIN_RATE_ANNUAL=.085
MAINTENANCE_RATIO=.25


def _score(prices, i):
    return .5*(prices[i-1]/prices[i-64]-1)+.5*(prices[i-1]/prices[i-127]-1)


def weights(model, symbols, closes, i, metadata, max_weight):
    """Signed target notionals / equity. No price at i or afterward is read."""
    if model not in MODELS:raise ValueError("Unknown experimental strategy model")
    if i<pr.WARMUP:raise ValueError("Insufficient lagged history")
    inv={s:1/pr._vol(closes[s],i) for s in symbols}
    momentum={s:_score(closes[s],i) for s in symbols}
    group={s:metadata[s]["group"] for s in symbols}
    defensive=[s for s in symbols if group[s] in ("bond","commodity")]
    equity=[s for s in symbols if group[s]=="equity"]
    target={s:0. for s in symbols}
    if model in ("defensive_rotation","diversified_risk_parity","equity_hedge"):
        if not defensive or not equity:
            raise ValueError("Needs equity and actual defensive instruments")
        if model=="diversified_risk_parity":
            active=symbols
            limits={"equity":.45,"bond":.30,"commodity":.20,"real_estate":.12,"crypto":.05}
            gross=.95
        elif model=="defensive_rotation":
            # Regime is determined by *previous* equity price vs its prior
            # 126-day average; no fabricated hedge return series.
            healthy=sum(closes[s][i-1]>mean(closes[s][i-126:i]) for s in equity)
            risk_on=healthy>=math.ceil(len(equity)/2)
            active=(equity if risk_on else defensive)
            limits=({"equity":.65,"bond":.25,"commodity":.15} if risk_on
                    else {"equity":0.,"bond":.55,"commodity":.35})
            gross=.95
        else:
            active=symbols
            limits={"equity":.50,"bond":.30,"commodity":.20}
            gross=.90
        total=sum(inv[s] for s in active)
        if total<=0:return target
        for s in active:target[s]=min(max_weight,gross*inv[s]/total)
        for g,cap in limits.items():
            members=[s for s in active if group[s]==g]
            exposure=sum(target[s] for s in members)
            if exposure>cap:
                for s in members:target[s]*=cap/exposure
        return target
    if model=="leveraged_trend":
        if len(equity)<2:raise ValueError("Needs multiple actual equities")
        active=[s for s in equity if closes[s][i-1]>mean(closes[s][i-126:i])
                and momentum[s]>0]
        total=sum(inv[s] for s in active)
        # Gross leverage 1.35x, 40% max per asset; remaining cap is cash.
        for s in active:
            target[s]=min(max_weight,.40,1.35*inv[s]/total)
        return target
    if len(equity)<4:raise ValueError("Short research requires 4+ equities")
    ranked=sorted(equity,key=lambda s:(momentum[s],s))
    count=max(1,len(ranked)//3)
    shorts=ranked[:count];longs=ranked[-count:]
    long_budget=.65 if model=="market_neutral" else .95
    short_budget=.65 if model=="market_neutral" else .45
    for group_ids,side,budget in ((longs,1,long_budget),(shorts,-1,short_budget)):
        total=sum(inv[s] for s in group_ids)
        for s in group_ids:
            target[s]=side*min(max_weight,.40,budget*inv[s]/total)
    return target


def segment(model,symbols,market,metadata,start,stop,max_weight,*,broker=None):
    """Mark-to-market signed holdings; borrow/margin charge daily.

    This is an *experimental approximation*, not an exchange/prime-broker
    portfolio margin engine. It makes a margin call at next open if equity
    falls beneath the maintenance-ratio floor.
    """
    if model not in MODELS:raise ValueError("Unsupported research model")
    broker=broker or {}
    delay=int(broker.get("delay_sessions",1))
    if delay not in (1,2):raise ValueError("Unsupported fill delay")
    cadence=broker.get("rebalance_sessions",pr.REBALANCE_SESSIONS)
    if type(cadence) is not int or cadence not in pr.SUPPORTED_REBALANCE_SESSIONS:
        raise ValueError("Unsupported research rebalance cadence")
    slip=float(broker.get("slippage_bps",8))
    commission=float(broker.get("commission_usd",0))
    fx_bps=float(broker.get("fx_conversion_bps",0))
    currency=str(broker.get("base_currency","USD"))
    borrow=float(broker.get("short_borrow_rate_annual",BORROW_RATE_ANNUAL))
    margin=float(broker.get("margin_rate_annual",MARGIN_RATE_ANNUAL))
    if not all(math.isfinite(v) and 0<=v<=1e6 for v in (slip,commission,fx_bps)):
        raise ValueError("Invalid execution expenses")
    if currency not in ("USD","CAD") or not all(math.isfinite(v) and 0<=v<=2 for v in (borrow,margin)):
        raise ValueError("Invalid finance assumptions")
    cap=pr.STARTING_CAPITAL
    cash=cap;qty={s:0. for s in symbols}
    closes={s:[float(bar["close"]) for bar in market[s]] for s in symbols}
    executions=[];curve=[];rebalance_log=[]
    fees=financing=borrow_fees=turnover=0.
    gross_sum=net_sum=0.;peak_gross=0.
    margin_calls=0;liquidate=False;stopped=False
    short_count=0
    for i in range(start,stop):
        opens={s:float(market[s][i]["open"]) for s in symbols}
        closed={s:float(market[s][i]["close"]) for s in symbols}
        marked=lambda prices: cash+sum(qty[s]*prices[s] for s in symbols)
        if not stopped and ((i-start)%cadence==0 or liquidate):
            if liquidate:
                desired={s:0. for s in symbols}
                margin_calls+=1
            else:
                observed=max(pr.WARMUP,i-(delay-1))
                desired=weights(model,symbols,closes,observed,metadata,max_weight)
            equity=marked(opens)
            if equity<=0 or not math.isfinite(equity):
                stopped=True
            else:
                # Split all changes at zero to avoid disguising a new short as
                # a simple sell of held shares.
                target_qty={s:math.trunc(equity*desired[s]/opens[s]) for s in symbols}
                for side in ("sell","buy"):
                    for s in symbols:
                        change=target_qty[s]-qty[s]
                        if (side=="sell" and change>=0) or (side=="buy" and change<=0):
                            continue
                        change=math.trunc(change)
                        if change==0:continue
                        px=opens[s]*(1+(1 if change>0 else -1)*
                            (float(metadata[s]["spread_bps"])/2+slip)/10000)
                        n=abs(change)*px
                        fee=commission+(n*fx_bps/10000 if metadata[s]["currency"]!=currency else 0.)
                        # A true short position is represented by negative
                        # shares and a positive cash credit from the sale.
                        before=qty[s]
                        qty[s]+=change
                        cash-=change*px+fee
                        fees+=fee;turnover+=n
                        if qty[s]<0:short_count+=1
                        action=("short_sell" if change<0 and qty[s]<0 else
                                "cover" if change>0 and before<0 else
                                "buy" if change>0 else "sell")
                        executions.append({"time":market[s][i]["time"],"symbol":s,
                            "side":action,"quantity":abs(change),"price":round(px,5),
                            "fee":round(fee,4),"notional":round(n,2),
                            "execution":"next_session_open" if delay==1 else "second_session_open",
                            "research_only":True})
                equity=marked(opens)
                gross=sum(abs(qty[s]*opens[s]) for s in symbols)
                rebalance_log.append({"time":market[symbols[0]][i]["time"],
                    "weights":{s:round(qty[s]*opens[s]/equity,5) for s in symbols}
                    if equity>0 else {},
                    "gross_exposure_pct":round(gross/equity*100,2) if equity>0 else 0})
            liquidate=False
        # Daily carry. Flat loan & borrow rates are explicitly synthetic,
        # no share locate, rebate, dividends or intraday margin modeling.
        funding=max(0.,-cash)*margin/252
        shorts=sum(max(0.,-qty[s])*closed[s] for s in symbols)*borrow/252
        cash-=funding+shorts;financing+=funding;borrow_fees+=shorts
        equity=marked(closed)
        gross=sum(abs(qty[s]*closed[s]) for s in symbols)
        if not math.isfinite(equity) or equity<=0:
            # A wiped-out equity curve is terminal and cannot recover by
            # creating phantom portfolio capital in subsequent sessions.
            equity=.01;cash=equity;qty={s:0. for s in symbols};stopped=True
        elif gross>0 and equity/gross<MAINTENANCE_RATIO:
            liquidate=True
        gross_ratio=gross/max(equity,.01)
        net=sum(qty[s]*closed[s] for s in symbols)/max(equity,.01)
        gross_sum+=gross_ratio;net_sum+=net;peak_gross=max(peak_gross,gross_ratio)
        curve.append({"time":market[symbols[0]][i]["time"],"value":round(equity,4)})
    stat=_stats(curve,executions,cap)
    ending=curve[-1]["value"]
    stat.update({
        "fees":round(fees+financing+borrow_fees,2),
        "transaction_fees":round(fees,2),
        "margin_interest":round(financing,2),
        "short_borrow_cost":round(borrow_fees,2),
        "turnover_pct":round(turnover/cap*100,2),
        "ending_equity":round(ending,2),"starting_capital":cap,
        "average_invested_pct":round(100*gross_sum/(stop-start),2),
        "average_gross_exposure_pct":round(100*gross_sum/(stop-start),2),
        "average_net_exposure_pct":round(100*net_sum/(stop-start),2),
        "peak_gross_leverage":round(peak_gross,3),
        "margin_calls":margin_calls,
        "short_executions":short_count,
        "cash_pct":round(cash/max(ending,.01)*100,2),
        "final_weights_pct":{s:round(qty[s]*closes[s][stop-1]/max(ending,.01)*100,2) for s in symbols},
        "rebalances":rebalance_log,
        "research_only":True,
    })
    return stat


def scenario_grade(curve,market,symbols,start):
    """Validation-only realized performance by observed trailing market regime.

    Regimes determined from already-completed 20-session benchmark prices;
    never use future outcomes to label the next day's trading condition.
    """
    if not curve:return {"samples":0,"worst_regime_return_pct":0,"regimes":{}}
    closes={s:[float(b["close"]) for b in market[s]] for s in symbols}
    regimes={r:[] for r in ("rising_market","falling_market","high_volatility","ordinary")}
    series=[float(p["value"]) for p in curve]
    for offset in range(1,len(curve)):
        idx=start+offset
        if idx<25:continue
        x=[mean(closes[s][j]/closes[s][idx-21] for s in symbols)
           for j in range(idx-21,idx)]
        prior=x[-1]/x[0]-1
        changes=[b/a-1 for a,b in zip(x,x[1:])]
        vol=stdev(changes) if len(changes)>1 else 0.
        regime="high_volatility" if vol>.025 else "falling_market" if prior<-.04 else (
            "rising_market" if prior>.04 else "ordinary")
        p=series[offset]/series[offset-1]-1 if series[offset-1]>0 else -.99
        regimes[regime].append(p)
    output={}
    for name,rets in regimes.items():
        if not rets:continue
        compounded=1.
        for x in rets:compounded*=max(.001,1+x)
        output[name]={"observations":len(rets),
            "return_pct":round((compounded-1)*100,3),
            "positive_day_pct":round(100*sum(r>0 for r in rets)/len(rets),2),
            "worst_day_pct":round(100*min(rets),3)}
    worst=min((x["return_pct"] for x in output.values()),default=0)
    return {"samples":sum(len(x) for x in regimes.values()),
            "regimes":output,"worst_regime_return_pct":worst}
