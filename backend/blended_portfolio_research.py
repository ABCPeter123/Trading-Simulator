"""Shared-cash blended allocation research, long-only multi-model portfolios.

Unlike blending separately backtested equity curves, these allocations share
one cash ledger, trade netted orders only once per asset, and pay execution
costs once at the portfolio level. Every component signal is computed using
only completed daily closes; the existing next-session opening-fill simulator
handles actual hypothetical orders. No broker orders or live support.
"""
from __future__ import annotations

import math
from . import portfolio_research as pr, advanced_portfolio_research as adv

LONG_MODELS=frozenset(pr.MODELS) | (frozenset(adv.MODELS)-adv.RESEARCH_ONLY)


def validate_sleeves(sleeves):
    if not isinstance(sleeves,list) or not 2<=len(sleeves)<=3:
        raise ValueError("A blend requires two or three model sleeves.")
    if any(not isinstance(s,dict) or set(s)!={"model","weight_pct"} for s in sleeves):
        raise ValueError("Invalid model sleeve fields.")
    names=[]
    for sleeve in sleeves:
        model=sleeve["model"];share=sleeve["weight_pct"]
        if (not isinstance(model,str) or model not in LONG_MODELS or model in names
            or type(share) not in (int,float) or not math.isfinite(share)
            or share<=0 or share>100):
            raise ValueError("Invalid or duplicate long-only sleeve.")
        names.append(model)
    if abs(sum(s["weight_pct"] for s in sleeves)-100)>1e-7:
        raise ValueError("Sleeve weights must add to 100%.")
    return [{"model":s["model"],"weight_pct":float(s["weight_pct"])}
            for s in sleeves]


def blend_weights(sleeves,symbols,closes,i,metadata,max_weight,
                  gross_target,equity_cap,redistribute):
    """Convex combination of contemporaneously evaluated sleeve allocations.

    Sleeve exposure controls and final position/asset-class limits are applied
    before the shared portfolio can execute any order. Remaining allocation
    stays cash unless explicit redistribution is requested.
    """
    weights=validate_sleeves(sleeves)
    if not (0<=gross_target<=1 and 0<=equity_cap<=1):
        raise ValueError("Invalid blend allocation limits.")
    raw={s:0. for s in symbols}
    for sleeve in weights:
        model=sleeve["model"]
        if model in pr.MODELS:
            individual=pr._weights(model,symbols,closes,i,metadata,max_weight,
                                   gross_target=1.,equity_cap=1.,
                                   redistribute=False)
        else:
            individual=adv.weights(model,symbols,closes,i,metadata,max_weight)
        proportion=sleeve["weight_pct"]/100
        for symbol in symbols:
            allocation=individual[symbol]
            if allocation < -1e-10:
                raise ValueError("Signed position cannot enter shared cash account.")
            raw[symbol]+=proportion*max(0.,allocation)
    total=sum(raw.values())
    if total<=1e-12:
        return raw
    # A model can hold cash intentionally; do not force full investment here.
    scale=min(1.,gross_target/total)
    target={s:min(max_weight,raw[s]*scale) for s in symbols}
    caps={**pr.GROUP_CAPS,"equity":equity_cap}
    for group,cap in caps.items():
        names=[s for s in symbols if metadata[s]["group"]==group]
        exposure=sum(target[s] for s in names)
        if exposure>cap and exposure>0:
            for s in names:target[s]*=cap/exposure
    if redistribute:
        # Only rebalance into instruments already selected by some active
        # sleeve, observing all final asset- and category-concentration caps.
        for _ in range(128):
            remaining=gross_target-sum(target.values())
            if remaining<1e-8:break
            room={g:max(0.,limit-sum(target[s] for s in symbols
                                     if metadata[s]["group"]==g))
                  for g,limit in caps.items()}
            eligible=[s for s in symbols if raw[s]>0 and
                      target[s]<max_weight-1e-10 and
                      room.get(metadata[s]["group"],1.)>1e-10]
            if not eligible:break
            total_eligible=sum(raw[s] for s in eligible)
            extra={s:min(max_weight-target[s],remaining*raw[s]/total_eligible)
                   for s in eligible}
            for group,capacity in room.items():
                group_ids=[s for s in eligible if metadata[s]["group"]==group]
                group_extra=sum(extra[s] for s in group_ids)
                if group_extra>capacity and group_extra>0:
                    for s in group_ids:extra[s]*=capacity/group_extra
            progress=sum(extra.values())
            if progress<1e-10:break
            for s,inc in extra.items():target[s]+=inc
    return target


def segment(sleeves,symbols,market,metadata,start,stop,max_weight,*,broker=None):
    """Execute all blend sleeves in a single cash and fee ledger."""
    sleeves=validate_sleeves(sleeves)
    def allocate(assets,closes,i,meta,cap,gross,equity,redistribute):
        return blend_weights(sleeves,assets,closes,i,meta,cap,gross,equity,redistribute)
    result=pr._segment("equal_weight",symbols,market,metadata,start,stop,
                       max_weight,broker=broker,allocator=allocate)
    result["sleeves"]=sleeves
    result["research_only"]=True
    return result
