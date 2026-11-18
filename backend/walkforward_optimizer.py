"""Private rolling walk-forward *selection* of portfolio models and exposure parameters.

Four expanding training windows select one candidate EACH from completed history,
then test on subsequent unseen dates. The last 20% is an untouched final audit.
This is not a broker-trading engine or a guarantee of target performance.
"""
from __future__ import annotations

from datetime import datetime, timezone
from itertools import product
import json
from math import erfc, isfinite, sqrt
from fastapi import HTTPException

from . import advanced_portfolio_research as adv
from . import blended_portfolio_research as blended
from . import performance_objectives as objectives
from . import selection_diagnostics as selection_bias
from . import portfolio_research as pr
from . import tournament_strategies as tournament
from . import universe_research as universe

SELECTION_FRACTIONS=(.50,.60,.70,.80,1.)
MAX_CANDIDATES={"focused":12,"extended":24,"comprehensive":48}


def validate_request(payload):
    if not isinstance(payload,dict):
        raise HTTPException(422,"Invalid walk-forward study.")
    spec=tournament.validate_spec(payload.get("spec"))
    width=payload.get("search_width","focused")
    if width not in MAX_CANDIDATES:
        raise HTTPException(422,"Search width must be focused, extended or comprehensive.")
    params={"target_cagr_pct":payload.get("target_cagr_pct",55.),
            "target_sharpe":payload.get("target_sharpe",2.),
            "risk_free_pct":payload.get("risk_free_pct",3.),
            "max_drawdown_pct":payload.get("max_drawdown_pct",30.),
            "slippage_bps":payload.get("slippage_bps",8.),
            "commission_usd":payload.get("commission_usd",0.),
            "fx_conversion_bps":payload.get("fx_conversion_bps",150.)}
    limits={"target_cagr_pct":(10,100),"target_sharpe":(.5,5),
            "risk_free_pct":(0,15),"max_drawdown_pct":(5,60),
            "slippage_bps":(0,100),"commission_usd":(0,30),
            "fx_conversion_bps":(0,300)}
    for name,value in params.items():
        lo,hi=limits[name]
        if type(value) not in (int,float) or not isfinite(value) or not lo<=value<=hi:
            raise HTTPException(422,f"Invalid {name} research parameter.")
    currency=payload.get("base_currency","USD")
    if currency not in ("USD","CAD"):
        raise HTTPException(422,"Invalid base currency.")
    return {"spec":spec,"search_width":width,"base_currency":currency,
            **{k:float(v) for k,v in params.items()}}


def candidates(spec, width="focused"):
    """Public, reproducible search grid. Private selected parameters stay local.

    Include the initial model first and search other compatible model families.
    Nested variant ordering is fixed, so a repeat study has identical trials.
    """
    is_blend=spec["model"]=="blended_portfolio"
    if spec["model"] in adv.RESEARCH_ONLY:
        models=[spec["model"], *[m for m in sorted(adv.RESEARCH_ONLY) if m!=spec["model"]]]
    else:
        all_long=[*pr.MODELS, *[m for m in adv.MODELS if m not in adv.RESEARCH_ONLY]]
        models=all_long if is_blend else [spec["model"], *[m for m in all_long if m!=spec["model"]]]
    cap=float(spec["max_position_pct"])
    caps=list(dict.fromkeys((cap,min(50.,max(10.,cap+10.)))))
    base_target=float(spec.get("target_investment_pct",95.))
    base_equity=float(spec.get("equity_class_cap_pct",70.))
    base_redistribute=bool(spec.get("redistribute_excess",False))
    variants=[(cap,base_target,base_equity,base_redistribute)]
    variants += [
        (weight,target,equity,redistribute)
        for weight,target,equity,redistribute in product(
            caps, (base_target,100.), (base_equity,100.), (base_redistribute,True))
    ]
    # Put strategy combinations in the FIRST bounded search, instead of
    # exhausting the entire trial budget on minor settings of one model.
    # Signed short/margin portfolios remain on the original separate ledger.
    mixes=(
        (("relative_momentum",50),("trend_filter",50)),
        (("relative_momentum",60),("inverse_volatility",40)),
        (("trend_filter",50),("inverse_volatility",50)),
        (("relative_momentum",60),("defensive_rotation",40)),
        (("trend_filter",60),("equity_hedge",40)),
        (("relative_momentum",40),("trend_filter",35),("inverse_volatility",25)),
        (("relative_momentum",55),("diversified_risk_parity",45)),
    ) if spec["model"] not in adv.RESEARCH_ONLY else ()
    seen=set()
    if is_blend:
        # First try the exact, immutable multi-sleeve model that the owner
        # selected from the saved report, never replace it with equal weight.
        original={"model":"blended_portfolio",
                  "sleeves":blended.validate_sleeves(spec["sleeves"]),
                  "max_position_pct":cap,
                  "delay_sessions":spec["delay_sessions"],
                  "target_investment_pct":base_target,
                  "equity_class_cap_pct":base_equity,
                  "redistribute_excess":base_redistribute}
        key=("blended_portfolio",
             tuple((x["model"],x["weight_pct"]) for x in original["sleeves"]),
             variants[0])
        seen.add(key)
        yield original
    for variant_index,variant in enumerate(variants):
        for model in models:
            key=(model,variant) if model in pr.MODELS else (model,variant[0])
            if key in seen:continue
            seen.add(key)
            config={"model":model,"max_position_pct":variant[0],
                    "delay_sessions":spec["delay_sessions"]}
            if model in pr.MODELS:
                config.update(target_investment_pct=variant[1],
                              equity_class_cap_pct=variant[2],
                              redistribute_excess=variant[3])
            yield config
            if len(seen)>=MAX_CANDIDATES[width]:return
        if variant_index==0:
            for mix in mixes:
                key=("blended_portfolio",mix,variant)
                if key in seen:continue
                seen.add(key)
                yield {"model":"blended_portfolio",
                       "sleeves":[{"model":m,"weight_pct":w} for m,w in mix],
                       "max_position_pct":variant[0],
                       "delay_sessions":spec["delay_sessions"],
                       "target_investment_pct":variant[1],
                       "equity_class_cap_pct":variant[2],
                       "redistribute_excess":variant[3]}
                if len(seen)>=MAX_CANDIDATES[width]:return


def _execute(config,symbols,market,metadata,start,end,slippage,settings=None):
    broker={**universe.COST_ASSUMPTIONS,
            **{key:settings[key] for key in ("base_currency","commission_usd","fx_conversion_bps")
               if settings is not None and key in settings},
            "delay_sessions":config["delay_sessions"],
            "slippage_bps":slippage}
    if config["model"] in pr.MODELS or config["model"]=="blended_portfolio":
        broker.update(target_investment_pct=config["target_investment_pct"],
                      equity_class_cap_pct=config["equity_class_cap_pct"],
                      redistribute_excess=config["redistribute_excess"])
    if config["model"]=="blended_portfolio":
        return blended.segment(config["sleeves"],symbols,market,metadata,start,end,
                               config["max_position_pct"]/100,broker=broker)
    segment=pr._segment if config["model"] in pr.MODELS else adv.segment
    return segment(config["model"],symbols,market,metadata,start,end,
                   config["max_position_pct"]/100,broker=broker)


def _choose(configs,symbols,market,metadata,train_end,settings):
    """All candidate selection is performed only on bars BEFORE train_end."""
    valid=[]
    attempted=0
    for config in configs:
        attempted+=1
        try:
            train=_execute(config,symbols,market,metadata,pr.WARMUP,train_end,
                           settings["slippage_bps"],settings)
            score_details,quality,_=objectives.score_breakdown(
                train,train["equity_curve"],settings["risk_free_pct"],
                drawdown_limit=settings["max_drawdown_pct"],
                target_cagr_pct=settings["target_cagr_pct"],
                target_sharpe=settings["target_sharpe"])
            score=score_details["total"]
        except (ValueError,ArithmeticError,ZeroDivisionError):
            continue
        if (score<=-1e5 or train["trades"]<1 or train["average_invested_pct"]<5
            or abs(train["max_drawdown_pct"])>settings["max_drawdown_pct"]
            or train.get("margin_calls",0)):
            continue
        valid.append((score,config,quality,score_details))
    if not valid:
        return None,attempted,0
    # Stable ties: the fixed trial order is the deterministic tiebreaker.
    best=max(valid,key=lambda item:item[0])
    high_growth=max(valid,key=lambda item:
                    item[2]["cagr_pct"] if item[2]["cagr_pct"] is not None else float("-inf"))
    high_sharpe=max(valid,key=lambda item:
                    item[2]["excess_sharpe"] if item[2]["excess_sharpe"] is not None else float("-inf"))
    leaders={name:{"config":entry[1],"score":entry[0],"training":entry[2]}
             for name,entry in (("highest_growth",high_growth),
                                ("highest_sharpe",high_sharpe),
                                ("balanced",best))}
    return {"score":best[0],"config":best[1],"training":best[2],
            "score_breakdown":best[3],
            "training_leaders":leaders},attempted,len(valid)


def _chain_segments(segments):
    """Join independent walk-forward folds as a *normalized return index*.

    Portfolio positions and absolute ledger P&L are NOT carried between folds.
    The resulting index expresses sequential percentage returns, including
    an explicit rebalance/zero-position reset at each fold boundary.
    """
    level=pr.STARTING_CAPITAL
    out=[]
    for segment in segments:
        if not segment or not segment["equity_curve"]:
            raise ValueError("Walk-forward window has no marked positions.")
        for bar in segment["equity_curve"]:
            out.append({"time":bar["time"],
                        "value":round(level*bar["value"]/pr.STARTING_CAPITAL,4)})
        level=out[-1]["value"]
    return out


def _max_drawdown(curve):
    peak=pr.STARTING_CAPITAL
    draw=0.
    for bar in curve:
        peak=max(peak,float(bar["value"]))
        draw=min(draw,(float(bar["value"])/peak-1)*100)
    return round(draw,4)


def _trial_adjustment(sharpe,sessions,trial_count):
    """Illustrative Bonferroni one-sided normal approximation, NOT a DSR/PBO.

    This assumes independent Gaussian daily returns and ignores serial
    correlation, changing volatility and all untracked human trial choices.
    Use as a conservative multiplicity *warning*, never as proof of an edge.
    """
    if sharpe is None or sessions<30:
        return {"raw_approx_p":None,"bonferroni_approx_p":None,
                "assumed_trials":trial_count}
    z=sharpe*sqrt(sessions/252.)
    p=.5*erfc(z/sqrt(2.))
    return {"raw_approx_p":round(p,7),
            "bonferroni_approx_p":round(min(1.,p*trial_count),7),
            "assumed_trials":trial_count}


def analyze(payload, *, loader=None, report=None):
    settings=validate_request(payload)
    report=report or (lambda pct,stage:None)
    symbols=settings["spec"]["symbols"]
    load=loader or universe._read
    histories={}
    for index,symbol in enumerate(symbols):
        report(4+int(26*index/max(1,len(symbols))),"Reading actual historical instruments")
        histories[symbol]=load(symbol)
        if histories[symbol].get("is_demo") or not universe._quality(histories[symbol].get("bars")):
            raise ValueError("Insufficient valid actual historical price data.")
    if any(pr.get_instrument(s).currency=="CAD" for s in symbols):
        histories["usdcad"]=load("usdcad")
    report(34,"Aligning shared observed sessions")
    days,market,metadata,sources=pr._prepare(symbols,histories)
    n=len(days)
    points=[int(n*x) for x in SELECTION_FRACTIONS]
    if (points[0]-pr.WARMUP<90 or
        any(b-a<30 for a,b in zip(points,points[1:])) or
        points[-1]-points[-2]<126):
        return {"status":"insufficient_history",
                "sessions_available":n,"earliest_date":days[0],
                "latest_date":days[-1],
                "minimum_requirements":"At least 90 initial post-warmup training sessions, 30 sessions per validation fold and 126 untouched final-audit sessions.",
                "research_only":True,"no_real_orders":True}
    configs=list(candidates(settings["spec"],settings["search_width"]))
    folds=[]
    realized=[]
    for fold_idx in range(3):
        train_end=points[fold_idx]
        out_end=points[fold_idx+1]
        report(36+int(42*fold_idx/3),"Selecting parameters from past observations")
        selected,attempted,eligible=_choose(configs,symbols,market,metadata,
                                            train_end,settings)
        if selected is None:
            # A failed selection is a failed study, not a cherry-picked fold.
            return {"status":"no_eligible_candidate","fold_failed":fold_idx+1,
                    "candidate_count":len(configs),"research_only":True,
                    "no_real_orders":True,
                    "reason":"No candidate passed prior-period drawdown, trading and exposure checks."}
        result=_execute(selected["config"],symbols,market,metadata,
                        train_end,out_end,settings["slippage_bps"],settings)
        realized.append(result)
        fold_metrics=objectives.performance(result["equity_curve"],
                                             risk_free_pct=settings["risk_free_pct"])
        folds.append({"fold":fold_idx+1,
                      "training_end":days[train_end-1],
                      "out_of_sample_start":days[train_end],
                      "out_of_sample_end":days[out_end-1],
                      "training_sessions":train_end-pr.WARMUP,
                      "out_of_sample_sessions":out_end-train_end,
                      "trials_evaluated":attempted,"eligible_trials":eligible,
                      "selected":selected["config"],
                      "selection_score":selected["score"],
                      "selection_score_breakdown":selected["score_breakdown"],
                      "training_objectives":selected["training"],
                      "out_of_sample_objectives":fold_metrics,
                      "out_of_sample_return_pct":result["return_pct"],
                      "out_of_sample_drawdown_pct":result["max_drawdown_pct"],
                      "trades":result["trades"],"fees":result["fees"]})
    report(82,"Computing forward-only stitched validation index")
    stitched=_chain_segments(realized)
    walkforward=objectives.performance(stitched,risk_free_pct=settings["risk_free_pct"])
    walkforward_consistency=objectives.consistency(stitched,
                                                  target_cagr_pct=settings["target_cagr_pct"])
    test_start=points[3]
    report(88,"Training final choice without seeing the audit period")
    final_choice,attempted,eligible=_choose(configs,symbols,market,metadata,
                                             test_start,settings)
    if final_choice is None:
        return {"status":"no_eligible_candidate","fold_failed":"final",
                "candidate_count":len(configs),"research_only":True,
                "no_real_orders":True,
                "reason":"No candidate qualified on the pre-audit training sample."}
    # All competing curves are calculated entirely in the pre-audit period.
    # They remain in memory, and only aggregate diagnostics enter the local
    # private report. Retain attempted trials even when a model cannot run.
    report(89,"Evaluating pre-audit multiple-testing diagnostics")
    pre_audit_curves=[]
    for config in configs:
        try:
            historical=_execute(config,symbols,market,metadata,
                                pr.WARMUP,test_start,settings["slippage_bps"],settings)
            pre_audit_curves.append(historical["equity_curve"])
        except (ValueError,ArithmeticError,ZeroDivisionError):
            continue
    selected_training=_execute(final_choice["config"],symbols,market,metadata,
                               pr.WARMUP,test_start,settings["slippage_bps"],settings)
    selection_diagnostics=selection_bias.diagnose(
        selected_training["equity_curve"],pre_audit_curves,
        risk_free_pct=settings["risk_free_pct"],
        attempted_trials=len(configs))
    report(91,"Evaluating sealed final audit")
    final=_execute(final_choice["config"],symbols,market,metadata,
                   test_start,n,settings["slippage_bps"],settings)
    stress_config={**final_choice["config"],"delay_sessions":2}
    stress=_execute(stress_config,symbols,market,metadata,
                    test_start,n,max(20.,settings["slippage_bps"]),settings)
    audit=objectives.performance(final["equity_curve"],
                                   risk_free_pct=settings["risk_free_pct"])
    stress_quality=objectives.performance(stress["equity_curve"],
                                            risk_free_pct=settings["risk_free_pct"])
    audit_consistency=objectives.consistency(final["equity_curve"],
                                              target_cagr_pct=settings["target_cagr_pct"])
    # This secondary stress is reported ONLY after the selection is locked.
    severe=_execute(stress_config,symbols,market,metadata,test_start,n,
                    max(35.,settings["slippage_bps"]),settings)
    # Compare three PRIOR-SELECTED research objectives on the same sealed
    # historical audit. No one is re-ranked or promoted using audit outcomes.
    comparison=[]
    audit_cache={json.dumps(final_choice["config"],sort_keys=True):final}
    for objective_name,leader in final_choice["training_leaders"].items():
        config=leader["config"];key=json.dumps(config,sort_keys=True)
        if key not in audit_cache:
            audit_cache[key]=_execute(config,symbols,market,metadata,
                                      test_start,n,settings["slippage_bps"],settings)
        observed=audit_cache[key]
        comparison.append({
            "objective":objective_name,"selected":config,
            "training_objectives":leader["training"],
            "audit_objectives":objectives.performance(
                observed["equity_curve"],risk_free_pct=settings["risk_free_pct"]),
            "audit_return_pct":observed["return_pct"],
            "audit_drawdown_pct":observed["max_drawdown_pct"],
            "audit_trades":observed["trades"],
        })
    targets=(audit["cagr_pct"] is not None and audit["excess_sharpe"] is not None
             and audit["cagr_pct"]>=settings["target_cagr_pct"]
             and audit["excess_sharpe"]>=settings["target_sharpe"]
             and abs(final["max_drawdown_pct"])<=settings["max_drawdown_pct"])
    # Do not select a different model after looking at the final audit.
    report(96,"Saving independently audited historical report")
    return {
        "status":"completed",
        "research_only":True,"no_real_orders":True,
        "symbols":symbols,
        "coverage":{"first_date":days[0],"last_date":days[-1],
                    "shared_sessions":n,"warmup_sessions":pr.WARMUP},
        "execution_assumptions":{key:settings[key] for key in
              ("base_currency","commission_usd","fx_conversion_bps","slippage_bps")},
        "targets":{"cagr_pct":settings["target_cagr_pct"],
                   "excess_sharpe":settings["target_sharpe"],
                   "max_drawdown_pct":settings["max_drawdown_pct"],
                   "risk_free_pct":settings["risk_free_pct"]},
        "model_search":{"width":settings["search_width"],
                        "candidate_count":len(configs),
                        "total_train_evaluations":sum(x["trials_evaluated"] for x in folds)+attempted,
                        "candidate_scope":"Compatible models on the selected fixed basket. No symbol selection, intraday signals or unrestricted model synthesis.",
                        "pre_audit_selection_diagnostics":selection_diagnostics},
        "walk_forward":{
            "folds":folds,
            "positive_folds":sum(x["out_of_sample_return_pct"]>0 for x in folds),
            "fold_count":len(folds),
            "stitch_method":"Normalized compound index of independently reset fold returns. Each fold starts with virtual $100,000 and zero positions; there is no continuous executable ledger.",
            "aggregate_objectives":walkforward,
            "aggregate_drawdown_pct":_max_drawdown(stitched),
            "consistency":walkforward_consistency,
            "curve":stitched,
            "multiplicity_approximation":_trial_adjustment(
                walkforward["excess_sharpe"],walkforward["sessions"],len(configs)),
        },
        "final_audit":{
            "selected":final_choice["config"],
            "selection_score_breakdown":final_choice["score_breakdown"],
            "prior_selected_comparison":comparison,
            "selection_score":final_choice["score"],
            "trials_evaluated":attempted,"eligible_trials":eligible,
            "start_date":days[test_start],"end_date":days[-1],
            "sessions":n-test_start,
            "objectives":audit,"return_pct":final["return_pct"],
            "drawdown_pct":final["max_drawdown_pct"],
            "stress_objectives":stress_quality,
            "consistency":audit_consistency,
            "stress_return_pct":stress["return_pct"],
            "severe_stress_return_pct":severe["return_pct"],
            "execution_stress_scenarios":[
                {"name":"configured_next_open","delay_sessions":final_choice["config"]["delay_sessions"],
                 "slippage_bps":settings["slippage_bps"],"return_pct":final["return_pct"]},
                {"name":"two_session_20bps_floor","delay_sessions":2,
                 "slippage_bps":max(20.,settings["slippage_bps"]),
                 "return_pct":stress["return_pct"]},
                {"name":"two_session_35bps_floor","delay_sessions":2,
                 "slippage_bps":max(35.,settings["slippage_bps"]),
                 "return_pct":severe["return_pct"]}],
            "observed_targets_met":bool(targets),
            "trades":final["trades"],"fees":final["fees"],
            "curve":final["equity_curve"],
        },
        "limitations":[
            "Models and allocation parameters are reselected before each walk-forward fold from prior-only training data. No predictive model is fitted; each OOS fold and audit reset capital and positions.",
            "Three objective leaders (highest training growth, highest training Sharpe and balanced) are all chosen exclusively before the audit. Their final audit outcomes are comparison diagnostics, never a held-out selection mechanism.",
            "The final audit is never used to rank, select or retune candidates; do not manually retune based on this audit and still call it unseen.",
            "Long-only candidates include 2-3 strategy sleeves mixed before netted trades in a single shared-cash ledger. This is not a portfolio of independently realized strategy returns. Short and margin sleeves are excluded from these blends.",
            "Comprehensive search expands the bounded model and sleeve grid, not the universe of all possible asset combinations; held-out periods cannot be used to retune.",
            "A fixed public grid of compatible models and bounded capital/position parameters is searched; no unlimited parameter fitting, learned indicators or multi-basket model synthesis is implemented.",
            "Bonferroni-adjusted p is an illustrative Gaussian-i.i.d. approximation conditional on the tested grid, not robust statistical significance.",
            "The separate estimated Deflated Sharpe uses an independent-normal expected maximum and i.i.d. skew/kurtosis correction. The CSCV PBO uses nonchronological splits of pre-audit candidate returns; both are approximations, not proof of performance or substitutes for real walk-forward evidence.",
            "Actual instrument history remains susceptible to survivorship bias, incomplete corporate-action adjustment and limited historical coverage.",
            "Slippage, borrowing costs, spreads, commissions, FX and fills are assumed, not actual future broker executions. No paper-forward evidence is included.",
            "Rolling 252-session returns overlap and do not represent independent years. Calendar years only count when nearly complete; incomplete audit windows must show insufficient evidence instead of a made-up worst annual return.",
            "An observed annualized return over less than multiple full years is not evidence of consistent 50-60% annual performance.",
        ],
    }
