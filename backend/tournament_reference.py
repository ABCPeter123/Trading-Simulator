"""Diagnostic replay of the user's original tournament candidate.

This comparison is intentionally RETROSPECTIVE: the source candidate came
from a separate completed tournament and may have been selected using prices
inside the dates being compared. It can never count as an independent
walk-forward victory, influence candidate selection or promote live trades.

Source specifications and all output remain in the private job database.
The public source contains no owner-selected instruments or parameters.
"""
from __future__ import annotations

from math import isfinite

from . import advanced_portfolio_research as advanced
from . import blended_portfolio_research as blended
from . import performance_objectives as objectives
from . import portfolio_research as portfolio


def source_config(spec):
    """Preserve the exact tournament portfolio rule and exposure settings."""
    candidate={
        "model":spec["model"],
        "max_position_pct":spec["max_position_pct"],
        "delay_sessions":spec["delay_sessions"],
    }
    if candidate["model"] in portfolio.MODELS or candidate["model"]=="blended_portfolio":
        candidate.update({
            "target_investment_pct":spec.get("target_investment_pct",95.),
            "equity_class_cap_pct":spec.get("equity_class_cap_pct",70.),
            "redistribute_excess":spec.get("redistribute_excess",False),
        })
    if candidate["model"]=="blended_portfolio":
        candidate["sleeves"]=blended.validate_sleeves(spec["sleeves"])
    return candidate


def training_eligibility(training, details, settings, quality=None):
    """Reproduce the same training gates for a *post-hoc* source reference."""
    if details["total"]<=-1e5:return "insufficient_training_history"
    if training["trades"]<1:return "no_training_trades"
    if training["average_invested_pct"]<5:return "insufficient_training_exposure"
    if abs(training["max_drawdown_pct"])>settings["max_drawdown_pct"]:
        return "max_drawdown_limit"
    if training.get("margin_calls",0):return "margin_calls"
    if quality is not None:
        cagr=quality.get("cagr_pct")
        if cagr is None or cagr<settings.get("minimum_training_cagr_pct",0):
            return "minimum_training_growth_not_met"
        if cagr<(settings.get("risk_free_pct",0)+
                 settings.get("minimum_excess_cagr_pct_points",0)):
            return "minimum_excess_growth_not_met"
    if training["average_invested_pct"]<settings.get("min_average_invested_pct",5):
        return "minimum_investment_exposure_not_met"
    return "qualified"


def evaluate(config, symbols, market, metadata, training_end, start, stop,
             settings, executor):
    """Evaluate immutable source on prior and subsequent observed dates.

    No model fitting, tuning or future-aware selection occurs. The tuple
    includes a prior-only eligibility diagnostic; later prices cannot
    affect that eligibility result.
    """
    result={
        "status":"unavailable",
        "interpretation":"Retrospective tournament-selected reference; not independent unseen evidence.",
        "selected_by_walkforward":False,
        "selection_input":False,
        "research_only":True,
        "configuration":config,
        "reason":"The source strategy could not be simulated on this aligned period.",
    }
    try:
        train=executor(config,symbols,market,metadata,portfolio.WARMUP,
                       training_end,settings["slippage_bps"],settings)
        score_details,quality,_=objectives.score_breakdown(
            train,train["equity_curve"],settings["risk_free_pct"],
            drawdown_limit=settings["max_drawdown_pct"],
            target_cagr_pct=settings["target_cagr_pct"],
            target_sharpe=settings["target_sharpe"])
        gate=training_eligibility(train,score_details,settings,quality)
        subsequent=executor(config,symbols,market,metadata,
                            start,stop,settings["slippage_bps"],settings)
        audit=objectives.performance(
            subsequent["equity_curve"],risk_free_pct=settings["risk_free_pct"])
        if not all(isfinite(x) for x in (subsequent["return_pct"],
                                         subsequent["max_drawdown_pct"])):
            return result
    except (ArithmeticError,ValueError,ZeroDivisionError):
        return result
    return {
        "status":"available",
        "interpretation":"Retrospective tournament-selected reference; not independent unseen evidence.",
        "selected_by_walkforward":False,
        "selection_input":False,
        "research_only":True,
        "configuration":config,
        "training_gate":gate,
        "training_score":score_details["total"],
        "training_drawdown_pct":train["max_drawdown_pct"],
        "training_cagr_pct":quality["cagr_pct"],
        "training_excess_sharpe":quality["excess_sharpe"],
        "training_average_invested_pct":train["average_invested_pct"],
        "return_pct":round(subsequent["return_pct"],4),
        "cagr_pct":audit["cagr_pct"],
        "excess_sharpe":audit["excess_sharpe"],
        "drawdown_pct":round(subsequent["max_drawdown_pct"],4),
        "average_invested_pct":subsequent.get("average_invested_pct"),
        "turnover_pct":subsequent.get("turnover_pct"),
        "trades":subsequent["trades"],
    }
