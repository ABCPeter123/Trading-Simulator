"""Historical GBM scenario research. No provider future bars or price forecasts guaranteed.

Time unit = one observed candle (minute/hour/day), not one calendar day.
Sample historical *log returns* determine empirical step drift/volatility.
Simulated paths are hypothetical, seeded, and never fed into actual fills.
"""
from __future__ import annotations
from math import erf, exp, isfinite, log, sqrt
from random import Random
from statistics import mean, stdev
from fastapi import HTTPException

MIN_RETURNS = 20
MAX_LOOKBACK = 252
MAX_HORIZON = 60
PATHS = 256

def estimate(bars: list[dict], lookback: int = 60):
    if not 20 <= lookback <= MAX_LOOKBACK:
        raise HTTPException(422, detail="Forecast lookback must be 20-252 candles.")
    closes = [float(b["close"]) for b in bars[-(lookback+1):]]
    if len(closes) < MIN_RETURNS+1 or any(not isfinite(x) or x <= 0 for x in closes):
        raise HTTPException(422, detail="At least 21 valid revealed close prices are required.")
    returns = [log(b/a) for a,b in zip(closes,closes[1:])]
    volatility = stdev(returns)
    if not isfinite(volatility):
        raise HTTPException(422, detail="Invalid historical volatility.")
    return {"spot": closes[-1], "mu_log": mean(returns),
            "sigma_step": volatility, "observations": len(returns)}

def probability_up(bars: list[dict], horizon: int, lookback: int = 60):
    """Historical physical-drift GBM chance of ending above today's spot."""
    if not 1 <= horizon <= MAX_HORIZON:
        raise HTTPException(422, detail="Forecast horizon must be 1-60 candles.")
    if len(bars) < MIN_RETURNS+1:
        return None
    params = estimate(bars, lookback)
    drift = params["mu_log"]
    sigma = params["sigma_step"]
    if sigma < 1e-12:
        if drift > 0: return 100.0
        if drift < 0: return 0.0
        return 50.0
    z = drift*sqrt(horizon)/sigma
    return 50 * (1 + erf(z/sqrt(2)))

def black_scholes(spot: float, strike: float, maturity_years: float,
                  vol_annual: float, rate: float = .03, yield_rate: float = 0):
    """European option theoretical valuation under risk-neutral GBM.

    This is an option-pricing model, NOT a price prediction.
    """
    if not (spot > 0 and strike > 0 and maturity_years > 0 and vol_annual >= 0
            and all(isfinite(x) for x in (spot,strike,maturity_years,vol_annual,rate,yield_rate))):
        raise HTTPException(422, detail="Invalid Black-Scholes parameters.")
    disc_s=spot*exp(-yield_rate*maturity_years)
    disc_k=strike*exp(-rate*maturity_years)
    if vol_annual < 1e-12:
        return {"call": max(0.,disc_s-disc_k), "put": max(0.,disc_k-disc_s)}
    d1=(log(spot/strike)+(rate-yield_rate+.5*vol_annual**2)*maturity_years)/(vol_annual*sqrt(maturity_years))
    d2=d1-vol_annual*sqrt(maturity_years)
    n=lambda x: .5*(1+erf(x/sqrt(2)))
    call=disc_s*n(d1)-disc_k*n(d2)
    put=disc_k*n(-d2)-disc_s*n(-d1)
    return {"call": max(0,call), "put": max(0,put)}

def simulate(bars: list[dict], horizon: int = 20, lookback: int = 60,
             paths: int = PATHS, seed: int = 0):
    if not 1 <= horizon <= MAX_HORIZON or paths != PATHS:
        raise HTTPException(422, detail="Forecast requires 1-60 horizon candles and 256 paths.")
    p=estimate(bars,lookback)
    rng=Random(seed)
    spot,mu,sigma=p["spot"],p["mu_log"],p["sigma_step"]
    # Store all paths for a fan chart, cap at 60x256.
    trajectories=[]
    for _ in range(paths):
        price=spot
        path=[spot]
        for _ in range(horizon):
            price *= exp(max(-10,min(10,mu+sigma*rng.gauss(0,1))))
            path.append(price)
        trajectories.append(path)
    distribution=[]
    for t in range(horizon+1):
        sorted_prices=sorted(row[t] for row in trajectories)
        distribution.append({"step":t,
            "p05":sorted_prices[int(.05*(paths-1))],
            "p25":sorted_prices[int(.25*(paths-1))],
            "median":sorted_prices[int(.5*(paths-1))],
            "p75":sorted_prices[int(.75*(paths-1))],
            "p95":sorted_prices[int(.95*(paths-1))]})
    terminal=[p[-1] for p in trajectories]
    return {
        "method":"Geometric Brownian motion, fitted to observed log returns",
        "spot":spot, "horizon":horizon, "lookback":lookback,
        "paths_count":paths, "seed":seed, "mu_log_per_bar":mu,
        "sigma_per_bar":sigma, "observations":p["observations"],
        "prob_up_model_pct":probability_up(bars,horizon,lookback),
        "prob_up_simulated_pct":100*sum(x>spot for x in terminal)/paths,
        "expected_terminal":mean(terminal),
        "median_terminal":distribution[-1]["median"],
        "quantiles":distribution,
        "paths":trajectories,
        "limitations":("Hypothetical scenarios, not reliable future-price predictions. "
          "Historical drift/volatility may change; log returns assumed independent "
          "and normal. Assumes constant parameters and no jumps or fat tails. "
          "All horizon units are observed replay candles."),
    }

def forecast_for_game(mode: str, run_id: str, asset_id: str | None,
                      horizon: int, lookback: int, seed: int = 0):
    if mode == "single":
        from .arcade import get_run
        game = get_run(run_id)
        if asset_id and asset_id != game["asset_id"]:
            raise HTTPException(422, detail="Asset not in current replay.")
        asset_id=game["asset_id"]
        bars=game["bars"]
        reference=bars[-1]["time"]
    elif mode == "portfolio":
        from .portfolio_arcade import get_season
        game=get_season(run_id)
        if asset_id not in game["asset_ids"]:
            raise HTTPException(422, detail="Choose an asset in the current portfolio.")
        bars=game["bars"][asset_id]
        reference=bars[-1]["time"]
    else:
        raise HTTPException(422, detail="Unknown forecast mode.")
    # Fixed seed default makes the scenario chart reproducible for same state.
    forecast=simulate(bars,horizon,lookback,seed=seed or int(reference)%2147483647)
    return {"asset_id":asset_id,"as_of":reference,"resolution":game["resolution"],**forecast}
