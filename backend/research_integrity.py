"""Read-only, private evidence checks for pre-audit trading research.

Never changes model ranking, queries delisting histories, or repairs prices.
Synthetic fixtures can use the same verifier without external dependencies.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite

from . import portfolio_research as portfolio


def cash_cost_counterfactual(config, selected_train, symbols, market, metadata,
                             stop, settings, executor):
    """Training-only comparison. No audit or forward candles are accepted.

    Zero-cost replay measures an *execution-assumption sensitivity*, not an
    exact causal breakdown of costs: different fees can alter whole-share fills.
    Cash and category exposure are descriptive, not independently optimized.
    """
    start = portfolio.WARMUP
    no_costs = {**settings, "commission_usd": 0., "fx_conversion_bps": 0.,
                "slippage_bps": 0.}
    frictionless = executor(config, symbols, market, metadata, start, stop, 0., no_costs)
    broker = {"base_currency": settings["base_currency"],
              "commission_usd": settings["commission_usd"],
              "fx_conversion_bps": settings["fx_conversion_bps"],
              "slippage_bps": settings["slippage_bps"],
              "delay_sessions": config["delay_sessions"],
              "target_investment_pct": 95.,
              "equity_class_cap_pct": 70.,
              "redistribute_excess": False}
    equal = portfolio._segment(
        "equal_weight", symbols, market, metadata, start, stop,
        config["max_position_pct"] / 100., broker=broker)
    def summary(ledger):
        return {
            "return_pct": round(float(ledger["return_pct"]), 4),
            "average_gross_invested_pct": ledger.get(
                "average_gross_exposure_pct", ledger.get("average_invested_pct")),
            "turnover_pct_of_starting_capital": ledger.get("turnover_pct"),
            "fees_and_financing_usd": ledger.get("fees"),
            "maximum_drawdown_pct": ledger.get("max_drawdown_pct"),
        }
    selected = summary(selected_train)
    zero = summary(frictionless)
    equal_weight = summary(equal)
    return {
        "status": "available",
        "evidence_boundary": "training_only_before_final_audit",
        "training_sessions": stop - start,
        "selected_with_configured_costs": selected,
        "selected_zero_transaction_costs": zero,
        "same_basket_equal_weight_with_configured_costs": equal_weight,
        "estimated_cost_sensitivity_pct_points": round(
            zero["return_pct"] - selected["return_pct"], 4),
        "selected_minus_equal_weight_pct_points": round(
            selected["return_pct"] - equal_weight["return_pct"], 4),
        "interpretation": (
            "Pre-audit same-period replays. The zero-cost scenario also changes "
            "whole-share affordability; cost sensitivity is not exact cost "
            "attribution. Cash, exposure and category caps are descriptive, "
            "not proof of avoidable cash drag. No configuration is reselected."
        ),
        "used_for_selection": False,
    }


def data_provenance(symbols, histories, shared_days, metadata, sources):
    """Report what actual downloaded data proves and what it cannot prove.

    Data sources lacking explicit adjustment, delisting and point-in-time
    constituent metadata remain UNVERIFIED. Never label them corrected.
    """
    if not shared_days:
        raise ValueError("Missing common observation timeline.")
    all_dates = {}
    output = []
    for symbol in symbols:
        raw = histories[symbol]
        bars = raw["bars"]
        dates = [datetime.fromtimestamp(
            int(row["time"]), timezone.utc).date().isoformat() for row in bars]
        all_dates[symbol] = set(dates)
        adjustment = raw.get("price_adjustment")
        recognized = adjustment in ("raw", "split_adjusted", "total_return_adjusted")
        output.append({
            "symbol": symbol,
            "source": sources.get(symbol, "unidentified")[:160],
            "recorded_snapshot": bool(raw.get("offline_cache")),
            "currency": metadata[symbol]["currency"],
            "first_observed_date": dates[0],
            "last_observed_date": dates[-1],
            "observed_sessions": len(dates),
            "explicit_price_adjustment": adjustment if recognized else "unverified",
            "corporate_actions_verified": False,
            "delisting_history_verified": False,
            "point_in_time_membership_verified": False,
        })
    union = set.union(*(all_dates[s] for s in symbols))
    overlapping = [d for d in union if shared_days[0] <= d <= shared_days[-1]]
    for record in output:
        record["unmatched_dates_within_shared_span"] = sum(
            d not in all_dates[record["symbol"]] for d in overlapping)
    fx = {"status": "not_required"}
    if any(metadata[s]["currency"] == "CAD" for s in symbols):
        raw = histories.get("usdcad") or {}
        fx_bars = raw.get("bars") or []
        quotes = {}
        for bar in fx_bars:
            try:
                key = datetime.fromtimestamp(
                    int(bar["time"]), timezone.utc).date().isoformat()
                close = float(bar["close"])
            except (TypeError, KeyError, ValueError, OverflowError):
                continue
            if isfinite(close) and close > 0:
                quotes[key] = close
        from bisect import bisect_left
        from datetime import date
        fx_dates = sorted(quotes)
        cad_days = sorted(set.union(
            *(all_dates[s] for s in symbols if metadata[s]["currency"] == "CAD")))
        without_prior = 0
        future_lookups = 0
        for day in cad_days:
            pos = bisect_left(fx_dates, day) - 1
            if pos < 0 or (date.fromisoformat(day) -
                           date.fromisoformat(fx_dates[pos])).days > 5:
                without_prior += 1
            elif fx_dates[pos] >= day:
                future_lookups += 1
        fx = {
            "status": "previous_completed_close",
            "source": str(raw.get("source") or "unidentified")[:160],
            "observed_quotes": len(fx_dates),
            "cad_sessions_missing_recent_prior_quote": without_prior,
            "future_or_same_day_fx_lookups": future_lookups,
            "conversion_rule": "Previous completed USD/CAD close; maximum five calendar days.",
            "historical_fx_spreads_verified": False,
        }
    return {
        "status": "partial_verification",
        "basis": "historical_inputs_observed_in_this_study",
        "shared_start": shared_days[0],
        "shared_end": shared_days[-1],
        "shared_sessions": len(shared_days),
        "instruments": output,
        "fx": fx,
        "corporate_actions_verified": False,
        "delisted_instruments_included": "unverified",
        "historical_universe_membership": "unverified_current_catalog_selection",
        "can_certify_survivorship_free": False,
        "limitations": [
            "Yahoo candles are requested with auto_adjust=False in the default provider, but archived and externally supplied candles have no guaranteed adjustment metadata.",
            "Split and dividend adjustments require provider-level verification and corporate-action event histories; this report does not manufacture them.",
            "The research basket comes from a present-day instrument catalog. Historical constituents and delisted securities are not reconstructed.",
            "Different trading calendars create unmatched dates; these counts alone do not prove missing exchange sessions.",
            "USD/CAD conversion uses prior completed daily FX closes, not executable historical FX quotes.",
        ],
        "used_for_selection": False,
    }
