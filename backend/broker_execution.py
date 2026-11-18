"""Versioned, broker-aware *research assumptions*, never account verification.

Actual interest, FX rates, stock-loan locates, account permissions, execution
prices and margin rules change. A snapshot in this module is an editable
simulation assumption, NOT a quotation or authorization for live orders.
"""
from __future__ import annotations

import math

BROKERS=("legacy_research","wealthsimple","ibkr")
TIMINGS=("next_open","next_close")
BORROW_POLICIES=("block_unverified","assume_available_research")
ASSUMPTION_DATE="2026-11-18"
REFERENCES={
    "wealthsimple_margin":"https://help.wealthsimple.com/hc/en-ca/articles/33646742423195-Learn-about-fees-and-interest-in-a-margin-account",
    "wealthsimple_fx":"https://help.wealthsimple.com/hc/en-ca/articles/4415548242971-Convert-funds-between-CAD-and-USD",
    "wealthsimple_short":"https://help.wealthsimple.com/hc/en-ca/articles/33646380604187-Trade-options-in-a-margin-account",
    "ibkr_margin":"https://www.interactivebrokers.ca/en/index.php?f=46803",
    "ibkr_commission":"https://www.interactivebrokers.ca/en/index.php?f=49637",
    "ibkr_fx":"https://www.interactivebrokers.ca/en/pricing/commissions-spot-currencies.php",
    "ibkr_borrow":"https://www.interactivebrokers.ca/en/trading/short-securities-availability.php",
}


def normalize(settings=None):
    """Validate and freeze a broker-cost scenario for the paper-only ledger."""
    if not isinstance(settings,(dict,type(None))):
        raise ValueError("Invalid broker model.")
    data=settings or {}
    if set(data)-{"broker","account_type","capital_currency","borrow_policy",
                   "fill_timing","margin_rate_pct","short_borrow_rate_pct",
                   "slippage_bps","fx_spread_bps"}:
        raise ValueError("Unsupported broker assumption.")
    broker=data.get("broker","legacy_research")
    if broker not in BROKERS:raise ValueError("Unknown broker model.")
    defaults={
        "legacy_research":{"margin_rate_pct":8.5,"short_borrow_rate_pct":6.,
                           "slippage_bps":8.,"account_type":"margin"},
        "wealthsimple":{"margin_rate_pct":8.,"short_borrow_rate_pct":6.,
                        "slippage_bps":8.,"account_type":"cash"},
        "ibkr":{"margin_rate_pct":5.13,"short_borrow_rate_pct":6.,
                "slippage_bps":8.,"account_type":"margin"},
    }[broker]
    result={
        "broker":broker,"account_type":data.get("account_type",defaults["account_type"]),
        "capital_currency":data.get("capital_currency","USD"),
        "borrow_policy":data.get("borrow_policy","block_unverified"),
        "fill_timing":data.get("fill_timing","next_open"),
        "rate_snapshot_date":ASSUMPTION_DATE,
    }
    for key in ("margin_rate_pct","short_borrow_rate_pct","slippage_bps","fx_spread_bps"):
        fallback=0. if key=="fx_spread_bps" else defaults[key]
        value=data.get(key,fallback)
        if type(value) not in (int,float) or not math.isfinite(value):
            raise ValueError("Nonfinite broker assumption.")
        hi=500. if key in ("slippage_bps","fx_spread_bps") else 100.
        if not 0<=value<=hi:raise ValueError("Broker cost assumption outside supported range.")
        result[key]=float(value)
    if (result["account_type"] not in ("cash","margin")
        or result["capital_currency"] not in ("USD","CAD")
        or result["borrow_policy"] not in BORROW_POLICIES
        or result["fill_timing"] not in TIMINGS):
        raise ValueError("Unsupported broker account, currency, loan or fill window.")
    if result["account_type"]=="cash" and result["borrow_policy"]!="block_unverified":
        raise ValueError("Cash accounts cannot assume share borrowing.")
    if broker=="wealthsimple" and result["borrow_policy"]!="block_unverified":
        raise ValueError("Wealthsimple does not currently support short selling shares.")
    if broker=="wealthsimple" and result["capital_currency"]=="CAD" and result["account_type"]=="margin":
        # This model converts initial CAD capital to a segregated USD paper cash
        # balance. It cannot reproduce Wealthsimple's cross-currency margin
        # collateral/interest behavior, so do not approve this combination.
        raise ValueError("CAD-funded Wealthsimple margin collateral is not modeled.")
    return result


def check_model(profile, model):
    """Do not mistake research borrow assumptions for borrow approval."""
    if model in ("long_short_momentum","market_neutral"):
        if profile["account_type"]!="margin" or profile["broker"]=="wealthsimple":
            raise ValueError("Short shares are not available in this broker account scenario.")
        if profile["broker"]!="legacy_research" and profile["borrow_policy"]!="assume_available_research":
            raise ValueError("Short research requires explicit unverified borrow assumption.")
    if model=="leveraged_trend" and profile["account_type"]!="margin":
        raise ValueError("Leveraged share exposure requires a simulated margin account.")


def fx_commission_usd(profile, cad_amount, fx_rate):
    """One upfront CAD->USD conversion. USD always means USD/CAD quote."""
    if not math.isfinite(fx_rate) or fx_rate<=0 or not math.isfinite(cad_amount) or cad_amount<0:
        raise ValueError("Invalid FX conversion input.")
    usd=cad_amount/fx_rate
    broker=profile["broker"]
    if broker=="wealthsimple":
        # Fee tiers are per explicit CAD/USD account conversion (not stock
        # orders paid directly in CAD). The unknown corporate quote spread
        # is separately user-configurable.
        pct=(1.5 if cad_amount<10000 else
             1. if cad_amount<25000 else
             .5 if cad_amount<100000 else 0.)
        fee=usd*pct/100
    elif broker=="ibkr":
        # Manual spot conversion commission, not automatic FX conversion.
        fee=max(2.,usd*.2/10000)
    else:
        fee=0.
    spread=usd*profile["fx_spread_bps"]/10000
    return round(fee+spread,8)


def order_fee_usd(profile, quantity, notional):
    if quantity<=0 or notional<=0:return 0.
    if profile["broker"]=="ibkr":
        # Tier I U.S. stock commission before variable external fees. Tiered
        # plan $0.0035/share, $0.35 min, 1% notional max.
        return min(notional*.01,max(.35,quantity*.0035))
    return 0.


def margin_rate_pct(profile, negative_cash_usd, fx_rate=1.):
    """Research margin rate, Wealthsimple USD tiered loan assumption."""
    if profile["account_type"]=="cash":return 0.
    if profile["broker"]!="wealthsimple":return profile["margin_rate_pct"]
    # Use amount borrowed in CAD across accounts to establish tier, but we
    # cannot observe other Wealthsimple margin balances, so this is a proxy.
    cad=abs(negative_cash_usd)*fx_rate
    if cad < 10000:return 8.
    if cad < 50000:return 7.9
    if cad < 100000:return 7.75
    if cad < 500000:return 7.7
    if cad < 1000000:return 6.95
    if cad < 2500000:return 6.2
    if cad < 5000000:return 5.6
    if cad < 10000000:return 5.15
    return 4.5


def cost_snapshot(profile):
    return {
        "broker":profile["broker"],"account_type":profile["account_type"],
        "pricing_date":profile["rate_snapshot_date"],"currency":profile["capital_currency"],
        "commission_assumption":"U.S. shares: IBKR tiered $0.0035/share, $0.35 min (before external fees); Wealthsimple $0",
        "borrowing_assumption":"Fixed user-editable annual short borrow rate, availability unverified",
        "fx_assumption":"One upfront CAD-to-USD conversion at prior completed FX close; variable executable market spread and cash collateral not verified",
        "fill_assumption":"Observed subsequent daily open/close, not intraday broker or tick data",
    }
