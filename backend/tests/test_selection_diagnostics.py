"""Independently invented return paths for pre-audit selection-bias tests."""
from __future__ import annotations

from math import sin

import pytest

from backend import selection_diagnostics as diagnostics


def to_curve(returns):
    capital = 100000.
    curve = []
    for i, daily in enumerate(returns):
        capital *= 1. + daily
        curve.append({"time": 1500000000 + i * 86400, "value": capital})
    return curve


def test_daily_returns_includes_first_session_commissions():
    curve = to_curve([-.002, .03, -.015])
    observed = diagnostics.daily_returns(curve)
    assert observed == pytest.approx([-.002, .03, -.015])
    assert diagnostics.daily_returns([{"value": float("nan")}]) is None
    assert diagnostics.daily_returns([]) is None


def test_cscv_detects_pre_audit_block_selection_instability():
    days = 480
    trials = []
    for candidate in range(8):
        trials.append([
            (.008 if day // 60 == candidate else -.0007) +
            .00002 * sin(day * .31 + candidate)
            for day in range(days)
        ])
    report = diagnostics.pbo_cscv(trials)
    assert report["status"] == "estimated_nonchronological_cscv"
    assert report["distinct_candidates"] == 8
    assert report["evaluated_splits"] == 70
    assert report["estimated_pbo_pct"] >= 75


def test_cscv_declines_to_report_distinctness_when_returns_identical():
    one = [.0002 + .003 * sin(i * .42) for i in range(320)]
    report = diagnostics.pbo_cscv([one, one[:], one[:], one[:]])
    assert report["status"] == "insufficient_distinct_trials"
    assert report["estimated_pbo_pct"] is None
    assert report["distinct_candidates"] == 1


def test_moment_adjustment_does_not_reward_increasing_number_of_trials():
    days = 400
    chosen = [.0008 + .01 * sin(i * .31) for i in range(days)]
    alternatives = [
        [.0003 + (.009 + j * .0003) * sin(i * .27 + j) for i in range(days)]
        for j in range(5)
    ]
    five = diagnostics.deflated_sharpe(chosen, alternatives,
                                       attempted_trials=5)
    fifty = diagnostics.deflated_sharpe(chosen, alternatives,
                                        attempted_trials=50)
    assert five["status"] == "estimated_iid_only"
    assert five["expected_max_sharpe"] <= fifty["expected_max_sharpe"]
    assert five["probability_pct"] >= fifty["probability_pct"]
    assert diagnostics.deflated_sharpe(chosen[:50], alternatives)["status"] == "insufficient_evidence"


def test_diagnostics_reject_invalid_curve_alignment_and_excludes_raw_paths():
    a = to_curve([.0005 + .01 * sin(i * .19) for i in range(300)])
    b = to_curve([.0004 + .009 * sin(i * .29) for i in range(300)])
    c = to_curve([.0002 + .013 * sin(i * .39) for i in range(300)])
    result = diagnostics.diagnose(a, [a, b, c], attempted_trials=7)
    assert result["attempted_candidates"] == 7
    assert "selected" not in result
    assert "curves" not in str(result).lower()
    assert result["deflated_sharpe"]["assumed_trials"] == 7
    with pytest.raises(ValueError, match="exact pre-audit"):
        diagnostics.diagnose(a, [b[:-1]])
    with pytest.raises(ValueError, match="understate"):
        diagnostics.deflated_sharpe([.01] * 300, [[.002] * 300] * 4,
                                   attempted_trials=3)
