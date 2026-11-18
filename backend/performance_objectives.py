"""Validation-only, research-grade objectives for high-performance portfolios.

This is an *evaluation and ranking* mode, not a guarantee or a trained model.
It uses net marked-to-market equity curves from the existing execution engine.
The last chronological 20% of market history must never enter selection.
"""
from __future__ import annotations

import math
from statistics import mean, stdev

SESSIONS_PER_YEAR = 252
TARGET_CAGR_PCT = 55.0
TARGET_SHARPE = 2.0


def performance(curve, starting_capital=100000., risk_free_pct=3.):
    """Annualized geometric growth and excess-return Sharpe.

    This uses a FIXED annual risk-free cash-rate *assumption*, not a
    historically fetched rate curve. It cannot substitute for a cash ledger
    earning interest. The first observed session includes its return from
    starting capital, including the initial modeled trade costs.
    """
    if not curve or starting_capital <= 0 or not all(
        math.isfinite(float(x.get("value", 0))) and float(x.get("value",0)) > 0
        for x in curve
    ):
        return {"cagr_pct": None, "excess_sharpe": None,
                "annualized_volatility_pct": None, "sessions": 0}
    vals = [starting_capital] + [float(x["value"]) for x in curve]
    returns = [b/a - 1 for a, b in zip(vals, vals[1:])]
    n = len(returns)
    ending = vals[-1]
    cagr = (math.exp(math.log(ending/starting_capital) *
                     SESSIONS_PER_YEAR/n) - 1)*100 if ending>0 else -100.
    volatility = stdev(returns) if n>=2 else 0.
    cash_rate = (1+risk_free_pct/100)**(1/SESSIONS_PER_YEAR)-1
    sharpe = ((mean(returns)-cash_rate)/volatility *
              math.sqrt(SESSIONS_PER_YEAR)) if volatility>1e-12 else None
    return {
        "cagr_pct": round(cagr, 4) if math.isfinite(cagr) else None,
        "excess_sharpe": round(sharpe, 4) if sharpe is not None and math.isfinite(sharpe) else None,
        "annualized_volatility_pct": round(volatility*math.sqrt(SESSIONS_PER_YEAR)*100,4),
        "sessions":n,
    }


def validation_windows(curve, risk_free_pct=3., windows=3, capital=100000.):
    """Evaluate successive validation subperiods, never the held-out test.

    All windows use an existing validation-only equity curve, with no
    refitting. Starting equity for each window is the previous session's
    observed equity, so returns telescope without resetting the portfolio.
    These are stability *diagnostics*, NOT independent walk-forward refits.
    """
    n=len(curve)
    if n < windows*30:
        return {"windows":[], "positive_windows":0, "window_count":0,
                "worst_window_return_pct":None, "all_windows_positive":False,
                "sufficient_history":False}
    parts=[]
    for k in range(windows):
        a=n*k//windows
        b=n*(k+1)//windows
        start_equity = float(curve[a-1]["value"]) if a else capital
        subset=curve[a:b]
        stats=performance(subset,start_equity,risk_free_pct)
        raw_return=(float(subset[-1]["value"])/start_equity-1)*100
        parts.append({
            "start":subset[0]["time"], "end":subset[-1]["time"],
            "sessions":len(subset), "return_pct":round(raw_return,4),
            "cagr_pct":stats["cagr_pct"],
            "excess_sharpe":stats["excess_sharpe"],
        })
    return {"windows":parts,
            "positive_windows":sum(x["return_pct"]>0 for x in parts),
            "window_count":windows,
            "worst_window_return_pct":min(x["return_pct"] for x in parts),
            "all_windows_positive":all(x["return_pct"]>0 for x in parts),
            "sufficient_history":True}


def score_breakdown(validation, curve, risk_free_pct=3., *,
                    drawdown_limit=30., target_cagr_pct=TARGET_CAGR_PCT,
                    target_sharpe=TARGET_SHARPE):
    """Auditable validation-only points. No held-out prices enter these terms.

    This is an intentionally heuristic ranking, NOT an expected-return estimate.
    Each debit is recorded separately so turnover is never an invisible penalty.
    """
    metrics=performance(curve,risk_free_pct=risk_free_pct)
    stability=validation_windows(curve,risk_free_pct=risk_free_pct)
    cagr=metrics["cagr_pct"]
    sharpe=metrics["excess_sharpe"]
    if cagr is None or not stability["sufficient_history"]:
        return {"eligible":False,"total":-1e6,
                "reason":"insufficient_validation_history",
                "components":{}},metrics,stability
    growth=max(-1.,min(1.5,cagr/target_cagr_pct))
    quality=max(-1.,min(1.5,(sharpe if sharpe is not None else -2.)/target_sharpe))
    drawdown=abs(float(validation.get("max_drawdown_pct",0)))
    turnover=max(0.,float(validation.get("turnover_pct",0)))
    missing=stability["window_count"]-stability["positive_windows"]
    components={
        "cagr_points":round(50*growth,6),
        "sharpe_points":round(50*quality,6),
        "drawdown_points":round(-.8*drawdown,6),
        "turnover_points":round(-.02*turnover,6),
        "losing_windows_points":round(-12*missing,6),
        "excess_drawdown_points":round(-2*max(0.,drawdown-drawdown_limit),6),
        "few_trades_points":-5. if int(validation.get("trades",0))<2 else 0.,
    }
    raw=(50*growth+50*quality-.8*drawdown-.02*turnover
         -12*missing-2*max(0.,drawdown-drawdown_limit)
         -(5 if int(validation.get("trades",0))<2 else 0))
    return {
        "eligible":True,"total":round(raw,4),
        "components":components,
        "inputs":{"validation_cagr_pct":cagr,
                  "validation_excess_sharpe":sharpe,
                  "max_drawdown_pct":float(validation.get("max_drawdown_pct",0)),
                  "turnover_pct":turnover,
                  "losing_validation_windows":missing,
                  "trades":int(validation.get("trades",0))},
        "target_cagr_pct":target_cagr_pct,"target_sharpe":target_sharpe,
        "drawdown_limit_pct":drawdown_limit,
        "definition":"Heuristic validation points, not return, probability or forecast.",
    },metrics,stability


def score(validation, curve, risk_free_pct=3., *, drawdown_limit=30.,
          target_cagr_pct=TARGET_CAGR_PCT,target_sharpe=TARGET_SHARPE):
    """Backward-compatible ranking tuple with a separate auditable breakdown."""
    details,metrics,stability=score_breakdown(
        validation,curve,risk_free_pct,drawdown_limit=drawdown_limit,
        target_cagr_pct=target_cagr_pct,target_sharpe=target_sharpe)
    return details["total"],metrics,stability

def consistency(curve,*,capital=100000.,target_cagr_pct=55.,year_sessions=252):
    """Observed rolling 252-session and sufficiently complete calendar-year returns.

    Rolling windows are heavily overlapping diagnostics, not independent
    annual trials. Calendar-year return excludes partial years, requiring
    first observed session by Jan 15, final by Dec 15, and >=200 sessions.
    Do not extrapolate a short held-out window to claim calendar consistency.
    """
    from datetime import datetime, timezone
    if (not isinstance(curve,list) or not math.isfinite(float(capital))
        or capital<=0 or not 0<target_cagr_pct<=100 or year_sessions<=0):
        raise ValueError("Invalid annual consistency inputs")
    vals=[float(capital)]+[float(x["value"]) for x in curve]
    if any(not math.isfinite(x) or x<=0 for x in vals):
        raise ValueError("Invalid observed equity curve")
    count=len(curve)
    returns=[(vals[i+year_sessions]/vals[i]-1)*100
             for i in range(count-year_sessions+1)] if count>=year_sessions else []
    groups={}
    for i,point in enumerate(curve):
        dt=datetime.fromtimestamp(int(point["time"]),timezone.utc).date()
        groups.setdefault(dt.year,[]).append((i,dt))
    years=[]
    for year,observations in sorted(groups.items()):
        a,first=observations[0]
        b,last=observations[-1]
        complete=(len(observations)>=200 and first.month==1
                  and first.day<=15 and last.month==12 and last.day>=15)
        first_value=vals[a]
        end_value=vals[b+1]
        years.append({"year":year,"sessions":len(observations),
                      "complete":complete,
                      "return_pct":round((end_value/first_value-1)*100,4)})
    eligible=[x for x in years if x["complete"]]
    return {"rolling_window_sessions":year_sessions,
            "rolling_windows":len(returns),
            "worst_rolling_12m_pct":round(min(returns),4) if returns else None,
            "best_rolling_12m_pct":round(max(returns),4) if returns else None,
            "positive_rolling_window_pct":round(sum(x>0 for x in returns)/len(returns)*100,2)
                if returns else None,
            "target_hit_rolling_window_pct":round(
                sum(x>=target_cagr_pct for x in returns)/len(returns)*100,2)
                if returns else None,
            "calendar_years":years,
            "complete_calendar_years":len(eligible),
            "worst_complete_calendar_year_pct":min(
                (x["return_pct"] for x in eligible),default=None),
            "all_complete_years_positive":all(x["return_pct"]>0 for x in eligible)
                if eligible else None,
            "interpretation":"Rolling periods overlap; partial years are excluded from worst full-year results."}


def dominates(a,b):
    """True if A is no worse on either validation objective and better on one."""
    ag, asr=a["validation_objectives"]["cagr_pct"],a["validation_objectives"]["excess_sharpe"]
    bg, bsr=b["validation_objectives"]["cagr_pct"],b["validation_objectives"]["excess_sharpe"]
    if None in (ag,asr,bg,bsr):
        return False
    return ag>=bg and asr>=bsr and (ag>bg or asr>bsr)
