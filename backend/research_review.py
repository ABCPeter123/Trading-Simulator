"""Local-only deterministic research critique with no model selection authority.

Consumes summary fields from an already completed walk-forward report. It never
accesses held-out candles, queues another job, changes weights, trains models,
or sends any owner-specific output to a third party.
"""
from __future__ import annotations

from math import isfinite


def _number(value):
    return float(value) if isinstance(value,(int,float)) and isfinite(value) else None


def review(result):
    """Return evidence-linked observations and safe next-study hypotheses.

    Audit-based findings are POST-HOC diagnostics. Next experiments may be
    designed from them, but MUST NOT reuse the opened audit as fresh evidence.
    """
    if result.get("status")!="completed":
        return {"status":"unavailable","reason":"Research has not completed."}
    audit=result["final_audit"]
    search=result["model_search"]
    folds=result["walk_forward"]["folds"]
    rate=result["targets"]["risk_free_pct"]
    score=search.get("pre_audit_candidate_leaderboard") or {}
    selected=audit["selected"]
    quality=audit["objectives"]
    exposure=audit.get("exposure_and_costs") or {}
    benchmark=audit.get("benchmark_comparison") or {}
    discovered=[]
    def add(code,severity,basis,description,observation):
        discovered.append({"code":code,"severity":severity,"basis":basis,
                           "observation":description,"evidence":observation})

    cagr=_number(quality.get("cagr_pct"))
    sharpe=_number(quality.get("excess_sharpe"))
    if cagr is not None and cagr<rate:
        add("below_cash_hurdle","high","sealed_audit",
            "The selected strategy grew more slowly than the assumed fixed cash-rate hurdle.",
            {"audit_cagr_pct":cagr,"cash_rate_assumption_pct":rate})
    if sharpe is not None and sharpe<=0:
        add("nonpositive_excess_sharpe","high","sealed_audit",
            "The audited excess Sharpe is not positive under the configured cash-rate assumption.",
            {"audit_excess_sharpe":sharpe})
    for ref in benchmark.get("benchmarks",[]):
        if ref.get("id")=="same_basket_equal_weight" and ref.get("return_pct",float("-inf"))>audit["return_pct"]:
            add("below_same_basket_baseline","medium","sealed_audit",
                "The selected allocation trails equal weight on the identical instruments and dates.",
                {"selected_return_pct":audit["return_pct"],
                 "same_basket_return_pct":ref["return_pct"]})
    external=audit.get("market_benchmark") or {}
    if external.get("status")=="available" and cagr is not None and external.get("cagr_pct",float("-inf"))>cagr:
        add("below_spy_price_benchmark","medium","sealed_audit",
            "The selected allocation trails the SPY price-only buy-and-hold reference.",
            {"selected_cagr_pct":cagr,"spy_price_cagr_pct":external["cagr_pct"]})
    gross=_number(exposure.get("average_gross_invested_pct"))
    if gross is not None and gross<50:
        add("low_invested_exposure","medium","sealed_audit",
            "Average gross exposure was below half of starting portfolio capital.",
            {"average_gross_invested_pct":gross})
    turnover=_number(exposure.get("turnover_pct_of_initial_capital"))
    if turnover is not None and turnover>250 and cagr is not None and cagr<6:
        add("high_turnover_weak_growth","medium","sealed_audit",
            "The portfolio traded heavily relative to starting capital while delivering low annual growth.",
            {"turnover_pct_initial_capital":turnover,"cagr_pct":cagr})
    if folds and len({repr(f["selected"]) for f in folds})==1:
        add("same_model_all_folds","info","pre_audit_walkforward",
            "All chronological folds independently selected the same configuration; model diversity is limited.",
            {"fold_count":len(folds)})
    stability=search.get("pre_audit_parameter_stability") or {}
    delta=_number(stability.get("cagr_range_pct_points"))
    if delta is not None and delta>=5:
        add("unstable_position_cap","medium","pre_audit_only",
            "Nearby position limits produce materially different pre-audit compound growth.",
            {"cagr_range_pct_points":delta})
    dsr=(search.get("pre_audit_selection_diagnostics") or {}).get("deflated_sharpe") or {}
    probability=_number(dsr.get("probability_pct"))
    if probability is not None and probability<5:
        add("weak_multiple_tested_sharpe","high","pre_audit_only",
            "Approximate deflated Sharpe does not support a convincing risk-adjusted edge.",
            {"estimated_probability_pct":probability})
    if score.get("eligible_count",0)<=1 and score.get("attempted_count",0)>1:
        add("few_eligible_training_models","medium","pre_audit_only",
            "Very few configurations passed the pre-audit risk/exposure constraints.",
            {"eligible":score["eligible_count"],"attempted":score["attempted_count"]})

    # Ideas are deliberately broad methodological investigations, not an
    # automated reaction using held-out prices to tune the winning model.
    proposals=[
        {"id":"compare_exposure_and_costs","priority":1,
         "title":"Audit cash drag and trade costs",
         "method":"Open the built-in pre-audit training cost counterfactual. Check invested exposure, turnover, fees, category caps, and the same-basket equal-weight control before designing any new parameter search.",
         "evidence_basis":"training_folds_and_diagnostics",
         "automatic_execution":False},
        {"id":"benchmark_over_new_sessions","priority":2,
         "title":"Gather genuinely new forward-paper evidence",
         "method":"Start private forward-paper monitoring for a frozen selection. Record new daily sessions and its activation-frozen equal-weight reference; never reconstruct an earlier unfrozen reference.",
         "evidence_basis":"future_not_yet_observed",
         "automatic_execution":False},
        {"id":"audit_data_provenance","priority":3,
         "title":"Verify market data and point-in-time survivorship",
         "method":"Inspect the source-by-source provenance report, previous-close FX coverage and unverified adjustment, delisting and historical-membership fields. Independent corporate-action and historical-universe data are still required.",
         "evidence_basis":"historical_data_quality",
         "automatic_execution":False},
    ]
    return {
        "status":"diagnostic_only","model":selected["model"],
        "findings":discovered,"next_experiments":proposals,
        "summary":{
            "audit_cagr_pct":cagr,"audit_excess_sharpe":sharpe,
            "assumed_cash_rate_pct":rate,
            "critical_findings":sum(x["severity"]=="high" for x in discovered),
            "training_candidates_eligible":score.get("eligible_count"),
            "training_candidates_attempted":score.get("attempted_count")},
        "integrity":{
            "audit_already_opened":True,
            "selection_changed":False,"experiments_queued":0,
            "read_only":True,"broker_orders":0,
            "warning":"The historical final audit has been observed. It cannot be called untouched evidence for any future model revision. Use fresh forward-paper periods."}
    }
