"""Bounded cross-universe basket discovery using training-only price history.

Selection screens on the earliest 60%-history cutoff across eligible symbols.
This deliberately sacrifices newer data rather than consulting the held-out
portion of any instrument during symbol selection. It cannot remove listing,
survivorship, universe-membership, or corporate-action biases.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from math import isfinite, sqrt
from statistics import mean, stdev

SIZES=(6,8,12,16)
MAX_EXTRA_BASKETS=16
POOL_PER_GROUP=14
_MIN_SCREEN=180
_MOMENTUM_LOOKBACK=126


def _date(stamp):
    return datetime.fromtimestamp(int(stamp), timezone.utc).date().isoformat()


def _cutoff(histories, eligible):
    return min(int(histories[s]["bars"][max(1,int(len(histories[s]["bars"])*.6)-1)]["time"])
               for s in eligible)


def _features(histories, eligible, group_for_symbol):
    """Read no bar later than the common, conservative screening cutoff."""
    cutoff=_cutoff(histories,eligible)
    scored=[]
    for symbol in eligible:
        bars=[b for b in histories[symbol]["bars"] if int(b["time"])<=cutoff]
        if len(bars)<_MIN_SCREEN:continue
        closes=[float(b["close"]) for b in bars]
        if any(not isfinite(v) or v<=0 for v in closes):continue
        returns={_date(b["time"]):closes[i]/closes[i-1]-1
                 for i,b in enumerate(bars) if i>0}
        recent=list(returns.values())[-100:]
        if len(recent)<60:continue
        vol=max(stdev(recent),.001)
        # Median-ish bounded rank inputs avoid an extreme historical winner
        # crowding out every lower-volatility defensive category.
        momentum=closes[-1]/closes[-1-_MOMENTUM_LOOKBACK]-1
        strength=max(-1.,min(2.,momentum))
        scored.append({"symbol":symbol,"group":group_for_symbol(symbol),
                       "strength":strength,"volatility":vol,
                       "observations":len(bars),"returns":returns})
    # Stable tie-breaks ensure runs are reproducible despite catalog order.
    scored.sort(key=lambda x:(-x["strength"],x["symbol"]))
    groups=defaultdict(list)
    for x in scored:groups[x["group"]].append(x)
    pool=[]
    for group in sorted(groups):
        group_items=groups[group]
        # Strong momentum leaders and low-volatility leaders both participate.
        kept={x["symbol"]:x for x in group_items[:POOL_PER_GROUP]}
        for x in sorted(group_items,key=lambda y:(y["volatility"],y["symbol"]))[:5]:
            kept[x["symbol"]]=x
        pool.extend(kept.values())
    return cutoff, sorted(pool,key=lambda x:x["symbol"]),len(scored)


def _correlation(a,b):
    common=sorted(set(a["returns"]).intersection(b["returns"]))
    if len(common)<40:return 1.
    common=common[-100:]
    xs=[a["returns"][d] for d in common]
    ys=[b["returns"][d] for d in common]
    mx,my=mean(xs),mean(ys)
    cross=sum((x-mx)*(y-my) for x,y in zip(xs,ys))
    scale=sqrt(sum((x-mx)**2 for x in xs)*sum((y-my)**2 for y in ys))
    # Constant-price instruments have undefined correlation. Fail
    # conservatively rather than pretending perfect diversification.
    return max(-1.,min(1.,cross/scale)) if scale>1e-12 else 1.


def _greedy(pool, target, style):
    """Training-only greedy construction with per-class and correlation budgets."""
    groups=defaultdict(list)
    for x in pool:groups[x["group"]].append(x)
    if len(pool)<2:return []
    chosen=[]
    group_count=defaultdict(int)
    group_targets={
        "diversified":{"equity":.5,"bond":.30,"commodity":.15,"real_estate":.10},
        "defensive":{"equity":.3,"bond":.50,"commodity":.25,"real_estate":.15},
        "momentum":{"equity":.75,"bond":.2,"commodity":.15,"real_estate":.1},
        "decorrelated":{"equity":.55,"bond":.35,"commodity":.2,"real_estate":.15},
    }[style]
    for _ in range(min(target,len(pool))):
        available=[]
        for item in pool:
            if item in chosen:continue
            group=item["group"]
            cap=max(1,int(target*group_targets.get(group,.15)+.5))
            if group_count[group]>=cap:continue
            # Correlation matters only after at least one candidate is chosen;
            # strong positive correlations are penalized, not prohibited.
            if chosen:
                correlation=mean(_correlation(item,other) for other in chosen)
                concentration=max(0.,correlation)
            else:concentration=0.
            strength=item["strength"]
            inverse_vol=1./(1.+item["volatility"]*60)
            if style=="momentum":
                quality=1.6*strength+.12*inverse_vol-.4*concentration
            elif style=="defensive":
                quality=.25*strength+1.5*inverse_vol-.6*concentration
            elif style=="decorrelated":
                quality=.35*strength+.4*inverse_vol-1.6*concentration
            else:
                quality=.6*strength+.7*inverse_vol-.9*concentration
            if group_count[group]==0 and len(chosen)>0:
                quality+=.2
            available.append((quality,item["symbol"],item))
        if not available:break
        selected=max(available,key=lambda z:(z[0],z[1]))[2]
        chosen.append(selected)
        group_count[selected["group"]]+=1
    return [x["symbol"] for x in chosen]


def discover(histories, eligible, group_for_symbol, *, max_extra=MAX_EXTRA_BASKETS):
    """Return at most max_extra unique training-screened multi-asset baskets.

    No validation or audit price is passed to the screening routines.
    The caller must still run independently aligned train/validation/audit
    periods for each candidate basket.
    """
    if not eligible:
        return {"baskets":[],"cutoff_session":None,"screened":0,
                "pool_size":0,"max_extra":max_extra,
                "method":"No eligible historical instruments."}
    if not isinstance(max_extra,int) or not 1<=max_extra<=MAX_EXTRA_BASKETS:
        raise ValueError("Invalid bounded basket-search budget.")
    cutoff,pool,scanned=_features(histories,eligible,group_for_symbol)
    result=[];seen=set()
    # Rotate styles first so even a small budget gets varied portfolio
    # structures, rather than exhausting its cap on one basket size.
    for size in SIZES:
        for style in ("diversified","decorrelated","defensive","momentum"):
            basket=_greedy(pool,size,style)
            key=tuple(sorted(basket))
            if len(basket)<2 or key in seen:continue
            seen.add(key)
            result.append((f"train_{style}_{size}",basket))
            if len(result)>=max_extra:break
        if len(result)>=max_extra:break
    # Use alternate deterministic rank slices to improve search breadth
    # without enumerating 2^N subsets or exceeding 16 instruments.
    for offset in (2,4,6,8):
        if len(result)>=max_extra:break
        rotated=pool[offset:]+pool[:offset]
        for size in (8,12):
            if len(result)>=max_extra:break
            basket=_greedy(rotated,size,"decorrelated")
            key=tuple(sorted(basket))
            if len(basket)>=2 and key not in seen:
                seen.add(key)
                result.append((f"train_decorrelated_offset_{offset}_{size}",basket))
    return {"baskets":result,
            "cutoff_session":_date(cutoff),"screened":scanned,
            "pool_size":len(pool),"max_extra":max_extra,
            "method":"Fixed bounded greedy basket search using historical momentum, "
                     "realized volatility, category caps, and pairwise daily-return "
                     "correlation. All measurements end no later than the earliest "
                     "60%-training cutoff among eligible histories; test and "
                     "validation candles never enter the asset screen."}
