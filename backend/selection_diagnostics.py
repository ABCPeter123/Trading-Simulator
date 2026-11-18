"""Pre-audit selection-bias diagnostics on local synthetic or observed portfolio curves.

The final audit is never an input. Cross-sectional combinatorially symmetric
cross-validation (CSCV) is a descriptive PBO approximation. The Deflated Sharpe
calculation uses an explicit i.i.d. moment approximation, *not* a validated
probability of profitability or a replacement for chronological walk-forward.
Do not publish owner strategy curves, selections or derived statistics.
"""
from __future__ import annotations

from itertools import combinations
from math import e, isfinite, log, sqrt
from statistics import NormalDist, mean, stdev

from .portfolio_research import STARTING_CAPITAL

TRADING_DAYS = 252
BLOCKS = 8
MIN_SESSIONS = 240
MIN_CANDIDATES = 3
EULER_MASCHERONI = 0.5772156649015329


def daily_returns(curve, capital=STARTING_CAPITAL):
    """Use the virtual initial capital to include first-session trading costs."""
    if not curve or not isfinite(capital) or capital <= 0:
        return None
    out = []
    prior = float(capital)
    for bar in curve:
        try:
            level = float(bar["value"])
        except (KeyError, ValueError, TypeError):
            return None
        if not isfinite(level) or level <= 0:
            return None
        out.append(level / prior - 1.)
        prior = level
    return out


def _cash_daily(risk_free_pct):
    if not isfinite(risk_free_pct) or not 0 <= risk_free_pct <= 15:
        raise ValueError("Invalid annual risk-free assumption")
    return (1. + risk_free_pct / 100.) ** (1. / TRADING_DAYS) - 1.


def _sharpe_daily(returns, cash):
    if len(returns) < 3:
        return None
    spread = stdev(returns)
    if spread < 1e-12:
        return None
    value = (mean(returns) - cash) / spread
    return value if isfinite(value) else None


def _expected_maximum(dispersion, trials):
    """Expected maximum of N zero-mean *independent normal* Sharpe estimates.

    Used only as a heuristic threshold. The actual candidates are correlated,
    and independently repeated/manual experiments are not fully counted.
    """
    if trials < 2 or dispersion <= 0:
        return 0.
    normal = NormalDist()
    n = float(trials)
    return dispersion * (
        (1. - EULER_MASCHERONI) * normal.inv_cdf(1. - 1. / n)
        + EULER_MASCHERONI * normal.inv_cdf(1. - 1. / (n * e))
    )


def deflated_sharpe(selected, competitors, risk_free_pct=3., attempted_trials=None):
    """Moment-adjusted estimated DSR of a *pre-audit* strategy selection.

    The threshold is the expected maximum null Sharpe across attempted
    configurations with at least the i.i.d. null dispersion 1/sqrt(T-1).
    Treat this as a diagnostic only. The calculation does not account for
    serial correlation, unrecorded experiments or nonstationary regimes.
    """
    insufficient = {"status": "insufficient_evidence",
                    "probability_pct": None, "expected_max_sharpe": None,
                    "annualized_selected_sharpe": None, "sessions": len(selected),
                    "assumed_trials": attempted_trials or len(competitors)}
    if len(selected) < MIN_SESSIONS or len(competitors) < MIN_CANDIDATES:
        return insufficient
    if attempted_trials is None:
        attempted_trials = len(competitors)
    if attempted_trials < len(competitors):
        raise ValueError("Attempted trial count cannot understate competitors.")
    cash = _cash_daily(risk_free_pct)
    estimate = _sharpe_daily(selected, cash)
    rival = [_sharpe_daily(x, cash) for x in competitors]
    rival = [x for x in rival if x is not None]
    if estimate is None or len(rival) < MIN_CANDIDATES:
        return insufficient
    n = len(selected)
    avg = mean(selected)
    std = stdev(selected)
    skew = mean(((x - avg) / std) ** 3 for x in selected)
    kurt = mean(((x - avg) / std) ** 4 for x in selected)
    variance = 1. - skew * estimate + (kurt - 1.) * estimate**2 / 4.
    if not isfinite(variance) or variance <= 1e-12:
        return insufficient
    null_dispersion = 1. / sqrt(n - 1.)
    trial_dispersion = max(null_dispersion, stdev(rival))
    threshold = _expected_maximum(trial_dispersion, attempted_trials)
    z = (estimate - threshold) * sqrt(n - 1.) / sqrt(variance)
    probability = NormalDist().cdf(z)
    return {
        "status": "estimated_iid_only",
        "probability_pct": round(100. * probability, 3),
        "expected_max_sharpe": round(threshold * sqrt(TRADING_DAYS), 4),
        "annualized_selected_sharpe": round(estimate * sqrt(TRADING_DAYS), 4),
        "sessions": n,
        "assumed_trials": attempted_trials,
        "valid_competitors": len(rival),
        "method": "Moment-adjusted Deflated Sharpe approximation with independent-normal expected-maximum threshold; dependent trading returns and correlated candidate trials violate its ideal assumptions.",
    }


def pbo_cscv(competitors, risk_free_pct=3., blocks=BLOCKS):
    """CSCV probability that IS winner ranks below median OOS.

    Splits the PRE-AUDIT period into eight consecutive blocks. Combinations
    of four blocks are used for fitting/ranking, complements for evaluation.
    They are NOT chronological walk-forward folds, and prices/positions are
    simulated on the full pre-audit path before subsetting daily returns.
    """
    result = {"status": "insufficient_evidence", "estimated_pbo_pct": None,
              "negative_logit_splits": 0, "evaluated_splits": 0,
              "distinct_candidates": 0, "blocks": blocks}
    if not competitors or not isinstance(blocks, int) or blocks < 4 or blocks % 2:
        return result
    n = len(competitors[0])
    if n < max(MIN_SESSIONS, 30 * blocks) or any(len(x) != n for x in competitors):
        return result
    if any(not all(isfinite(v) and v > -1 for v in x) for x in competitors):
        return result
    # Identical equity series are a single statistical strategy, even when
    # the model grid happened to assign two distinct names to the same trades.
    unique = list(dict.fromkeys(tuple(round(v, 12) for v in x) for x in competitors))
    result["distinct_candidates"] = len(unique)
    if len(unique) < MIN_CANDIDATES:
        result["status"] = "insufficient_distinct_trials"
        return result
    cash = _cash_daily(risk_free_pct)
    n_candidates = len(unique)
    indexes = [range(n * i // blocks, n * (i + 1) // blocks) for i in range(blocks)]
    logits = []
    for selected_blocks in combinations(range(blocks), blocks // 2):
        chosen = set(selected_blocks)
        train_idx = [j for i in range(blocks) if i in chosen for j in indexes[i]]
        test_idx = [j for i in range(blocks) if i not in chosen for j in indexes[i]]
        fit = [_sharpe_daily([series[j] for j in train_idx], cash) for series in unique]
        held = [_sharpe_daily([series[j] for j in test_idx], cash) for series in unique]
        if any(x is None for x in fit + held):
            continue
        winner = max(range(n_candidates), key=lambda j: fit[j])
        target = held[winner]
        below = sum(v < target - 1e-12 for v in held)
        ties = sum(abs(v - target) <= 1e-12 for v in held)
        # Average rank for ties avoids a false PBO signal when portfolios
        # generate identical performance in the held-out subset.
        rank = (below + ties / 2.) / n_candidates
        if not 0 < rank < 1:
            continue
        logits.append(log(rank / (1. - rank)))
    if not logits:
        result["status"] = "unidentifiable"
        return result
    negatives = sum(v < -1e-12 for v in logits)
    return {
        "status": "estimated_nonchronological_cscv",
        "estimated_pbo_pct": round(100. * negatives / len(logits), 2),
        "negative_logit_splits": negatives,
        "evaluated_splits": len(logits),
        "distinct_candidates": n_candidates,
        "blocks": blocks,
        "median_oos_rank_logit": round(sorted(logits)[len(logits) // 2], 5),
        "method": "Combinatorially symmetric cross-validation on pre-audit blocks; nonchronological, correlated, and conditional on a fixed set of candidate rules.",
    }


def diagnose(selected_curve, competitor_curves, *, risk_free_pct=3., attempted_trials=None):
    """Return aggregate-only diagnostics; do not reveal private trial curves."""
    selected = daily_returns(selected_curve)
    rivals = [daily_returns(curve) for curve in competitor_curves]
    rivals = [r for r in rivals if r is not None]
    if selected is None:
        raise ValueError("Invalid pre-audit selected equity curve.")
    if any(len(r) != len(selected) for r in rivals):
        raise ValueError("Candidate curves must share the exact pre-audit dates.")
    return {
        "basis": "Pre-audit training history only. Neither diagnostic reads the sealed final audit.",
        "valid_candidate_curves": len(rivals),
        "attempted_candidates": attempted_trials or len(competitor_curves),
        "deflated_sharpe": deflated_sharpe(
            selected, rivals, risk_free_pct, attempted_trials),
        "pbo": pbo_cscv(rivals, risk_free_pct),
    }
