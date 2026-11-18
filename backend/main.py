"""Local-only API. Start via: python -m uvicorn backend.main:app --reload"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
import os
import hmac
from . import bridge_password
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .assets import get_instrument, list_instruments, search_yahoo, import_yahoo
from .ledger import account_snapshot, reset_account, submit_order
from .market import history, quote, market_open
from .strategy import sma_backtest
from .archive import archive_stats
from .arcade import start_run, get_run, list_runs, submit_order as submit_arcade_order, cancel_order, set_strategy, advance_run, set_risk
from .arcade_dsl import compile_rules, EXAMPLES

# A public demo must never accidentally boot against the owner's private
# databases or paid/local AI provider. Fail closed before exposing any routes.
PUBLIC_DEMO = os.environ.get("TRADING_SIM_PUBLIC_DEMO") == "1"
if PUBLIC_DEMO:
    required = (
        "TRADING_SIM_ARCADE_DB", "TRADING_SIM_DB",
        "TRADING_SIM_STRATEGY_DB", "TRADING_SIM_CUSTOM_INSTRUMENTS",
        "TRADING_SIM_MARKET_DIR",
    )
    private_root = Path(__file__).resolve().parent.parent / "data"
    for variable in required:
        value = os.environ.get(variable)
        if not value:
            raise RuntimeError("Public demo requires isolated path: " + variable)
        if not Path(value).is_absolute() or Path(value).resolve().is_relative_to(private_root.resolve()):
            raise RuntimeError("Public demo path must be absolute and outside private data/: " + variable)
    if os.environ.get("TRADING_SIM_AI_PROVIDER") != "off":
        raise RuntimeError("Public demo cannot expose a local or paid AI provider.")

# The private API bridge is opt-in and protected by a long random bearer token.
# Vercel hosts ONLY static code. This service and its databases stay on the
# owner's computer; the temporary tunnel transports requests, not storage.
PRIVATE_BRIDGE = os.environ.get("TRADING_SIM_PRIVATE_BRIDGE") == "1"
BRIDGE_TOKEN = os.environ.get("TRADING_SIM_PRIVATE_API_TOKEN", "")
BRIDGE_PASSWORD_HASH = os.environ.get("TRADING_SIM_PRIVATE_PASSWORD_HASH", "")
BRIDGE_ORIGINS = [
    origin.strip().rstrip("/")
    for origin in os.environ.get("TRADING_SIM_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]
if PRIVATE_BRIDGE:
    if PUBLIC_DEMO:
        raise RuntimeError("A public shared demo cannot be a private trading bridge.")
    if not BRIDGE_PASSWORD_HASH and len(BRIDGE_TOKEN) < 48:
        raise RuntimeError("Private bridge requires a password verifier or a random API token of at least 48 characters.")
    if BRIDGE_PASSWORD_HASH and not BRIDGE_PASSWORD_HASH.startswith("pbkdf2-sha256$"):
        raise RuntimeError("Invalid private password verifier.")
    if not BRIDGE_ORIGINS or any(
        urlparse(origin).scheme != "https"
        or not urlparse(origin).hostname
        or urlparse(origin).path not in ("", "/")
        or urlparse(origin).query or urlparse(origin).fragment
        for origin in BRIDGE_ORIGINS
    ):
        raise RuntimeError("Private bridge requires exact HTTPS origins in TRADING_SIM_ALLOWED_ORIGINS.")

app = FastAPI(title="Trading Simulator Local API", version="1.1.0")

@app.exception_handler(RequestValidationError)
async def explain_invalid_request(_request: Request, exc: RequestValidationError):
    """Keep legacy Vercel clients actionable without returning submitted private values."""
    descriptions = {
        "missing": "is required",
        "float_parsing": "must be a number",
        "int_parsing": "must be a whole number",
        "float_type": "must be a number",
        "int_type": "must be a whole number",
        "string_type": "must be text",
        "literal_error": "must be one of the supported choices",
        "string_pattern_mismatch": "contains unsupported characters",
        "list_too_short": "has too few items",
        "list_too_long": "has too many items",
    }
    issues = []
    for error in exc.errors()[:3]:
        location = error.get("loc", ())
        field = ".".join(item for item in location[1:]
                         if isinstance(item, str) and item.isidentifier())
        kind = error.get("type", "")
        context = error.get("ctx", {})
        if not isinstance(context, dict):
            context = {}
        if kind == "greater_than_equal" and isinstance(context.get("ge"), (int, float)):
            hint = f"must be at least {context['ge']}"
        elif kind == "less_than_equal" and isinstance(context.get("le"), (int, float)):
            hint = f"must be at most {context['le']}"
        elif kind == "greater_than" and isinstance(context.get("gt"), (int, float)):
            hint = f"must be greater than {context['gt']}"
        elif kind == "less_than" and isinstance(context.get("lt"), (int, float)):
            hint = f"must be less than {context['lt']}"
        else:
            hint = descriptions.get(kind, "has an invalid value")
        issues.append(f"{field}: {hint}" if field else hint)
    return JSONResponse({"detail": "Invalid request: " + "; ".join(issues)},
                        status_code=422)


# The live strategy machine is disabled for shared public demos. It is an
# owner-only, durable private service, not a browser-based trading bot.
from .live_routes import router as private_live_router
app.include_router(private_live_router)
from .market_data_routes import router as market_data_router
app.include_router(market_data_router)
if PRIVATE_BRIDGE:
    app.add_middleware(
        CORSMiddleware, allow_origins=BRIDGE_ORIGINS,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
        allow_credentials=False, allow_private_network=True, max_age=600,
    )

@app.middleware("http")
async def protect_private_bridge(request: Request, call_next):
    if PRIVATE_BRIDGE and request.url.path.startswith("/api/"):
        origin = request.headers.get("origin")
        if origin and origin not in BRIDGE_ORIGINS:
            return JSONResponse({"detail": "Origin not authorized."}, status_code=403)
        expected = "Bearer " + BRIDGE_TOKEN
        # Browser password login is the only anonymous API action. Existing
        # token-mode connections remain supported for local legacy setups.
        login_route = BRIDGE_PASSWORD_HASH and request.url.path in ("/api/auth/login","/api/auth/status")
        authorized = (bridge_password.authenticated(request.headers.get("authorization",""))
                      if BRIDGE_PASSWORD_HASH else
                      hmac.compare_digest(request.headers.get("authorization",""),expected))
        if request.method != "OPTIONS" and not login_route and not authorized:
            denied = JSONResponse({"detail": "Private engine authorization required."}, status_code=401)
            denied.headers["Cache-Control"] = "no-store"
            if origin in BRIDGE_ORIGINS:
                # Let an authorized browser show a useful 401 message when a
                # token is mistyped, rather than an opaque CORS network error.
                denied.headers["Access-Control-Allow-Origin"] = origin
                denied.headers["Vary"] = "Origin"
            return denied
    response = await call_next(request)
    if PRIVATE_BRIDGE:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.method == "OPTIONS" and request.headers.get("origin") in BRIDGE_ORIGINS:
            # Chromium local-network preflight where applicable.
            response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response

class NewOrder(BaseModel):
    asset_id: str
    side: Literal["buy", "sell"]
    quantity: str = Field(min_length=1, max_length=40)

@app.get("/api/instruments")
def instruments(search: str = Query("", max_length=80), category: str = Query("", max_length=30), limit: int = Query(2000, ge=1, le=2000)):
    return list_instruments(search, category, limit)

class BridgeLogin(BaseModel):
    password: str = Field(min_length=1, max_length=128)

@app.get("/api/auth/status")
def bridge_auth_status():
    if not PRIVATE_BRIDGE or not BRIDGE_PASSWORD_HASH:
        raise HTTPException(404, detail="Password login unavailable.")
    return {"mode":"private-bridge-password","login":"password"}

@app.post("/api/auth/login")
def bridge_auth_login(body: BridgeLogin, request: Request):
    if not PRIVATE_BRIDGE or not BRIDGE_PASSWORD_HASH:
        raise HTTPException(404, detail="Password login unavailable.")
    # IP supplied by trusted Cloudflare connector; spoofing this header does
    # not bypass the global login-attempt budget.
    ip=request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")
    session=bridge_password.new_session(body.password,BRIDGE_PASSWORD_HASH,ip)
    if not session:
        raise HTTPException(401,detail="Incorrect password or too many attempts. Try again later.")
    return {"mode":"private-bridge","token":session,"expires_in":bridge_password.SESSION_SECONDS}

@app.post("/api/auth/logout")
def bridge_auth_logout(request: Request):
    if not PRIVATE_BRIDGE or not BRIDGE_PASSWORD_HASH:
        raise HTTPException(404,detail="Password logout unavailable.")
    bridge_password.revoke(request.headers.get("authorization",""))
    return {"logged_out":True}

@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "public-demo" if PUBLIC_DEMO else "private-bridge" if PRIVATE_BRIDGE else "local", "version": "1.1.0"}

@app.get("/api/market/{asset_id}")
def market_history(asset_id: str, range: str = Query("1M"), resolution: str | None = Query(None)):
    if resolution is None:
        return history(asset_id, range)  # existing consumers keep their original range behavior
    from .intraday import replay_history
    return replay_history(asset_id, range, resolution)

@app.get("/api/quotes/{asset_id}")
def market_quote(asset_id: str):
    return quote(asset_id)

@app.get("/api/account")
def get_account():
    unpriced = account_snapshot()
    prices = {}
    for position in unpriced["positions"]:
        try:
            prices[position["asset_id"]] = quote(position["asset_id"])
        except HTTPException:
            pass  # Report unpriced positions explicitly. Never invent marks.
    return account_snapshot(prices)

@app.post("/api/orders")
def place_order(order: NewOrder):
    instrument = get_instrument(order.asset_id)
    # Recheck session and actual quote timestamp per order, even if quote was cached.
    if not market_open(instrument):
        raise HTTPException(409, detail="Market session closed.")
    latest = quote(order.asset_id)
    quote_age = (datetime.now(timezone.utc) - datetime.fromisoformat(latest["timestamp"])).total_seconds()
    if not (-60 <= quote_age <= (120 if instrument.kind == "Crypto" else 1200)):
        raise HTTPException(409, detail="Price is stale. Please refresh before trading.")
    # The server obtains the reference quote; client-supplied prices are ignored.
    fill = submit_order(order.asset_id, order.side, order.quantity, latest)
    return {"fill": fill, "account": get_account()}

@app.post("/api/account/reset")
def reset():
    reset_account()
    return get_account()

@app.get("/api/backtest/{asset_id}")
def backtest(asset_id: str, fast: int = Query(10, ge=2, le=100), slow: int = Query(30, ge=3, le=100)):
    return sma_backtest(asset_id, fast, slow)

@app.get("/api/archive/{asset_id}")
def get_archive_stats(asset_id: str, range: str = Query("1Y")):
    return archive_stats(asset_id, range)

# Arcade endpoints never return candles beyond the current game timestamp.
class ArcadeStart(BaseModel):
    asset_id: str
    starting_point: float = Field(default=0.3, ge=0.15, le=0.75)
    period: Literal["7D", "30D", "60D", "6M", "1Y", "2Y", "5Y", "10Y", "MAX"] = "5Y"
    resolution: Literal["1m", "5m", "15m", "1h", "1d"] = "1d"
    start_date: str | None = Field(default=None, max_length=10)

class ArcadeOrder(BaseModel):
    side: Literal["buy", "sell"]
    kind: Literal["market", "limit", "stop"] = "market"
    size: str = Field(min_length=1, max_length=40)
    size_type: Literal["percent", "units"] = "percent"
    price: str | None = None

class ArcadeAdvance(BaseModel):
    count: int = Field(default=1, ge=1, le=100)
    until_action: bool = False

class ArcadeStrategy(BaseModel):
    code: str = Field(max_length=1800)

@app.get("/api/arcade/runs")
def arcade_runs():
    return list_runs()

@app.get("/api/arcade/examples")
def arcade_examples():
    return {"examples": EXAMPLES}

@app.post("/api/arcade/validate")
def arcade_validate(strategy: ArcadeStrategy):
    return {"valid": True, "rules": [rule.to_dict() for rule in compile_rules(strategy.code)]}

@app.post("/api/arcade/new")
def arcade_new(request: ArcadeStart):
    return start_run(request.asset_id, request.starting_point, request.period, request.start_date, request.resolution)

@app.get("/api/arcade/{run_id}")
def arcade_get(run_id: str):
    return get_run(run_id)

@app.post("/api/arcade/{run_id}/orders")
def arcade_order(run_id: str, order: ArcadeOrder):
    return submit_arcade_order(run_id, order.side, order.kind, order.size, order.size_type, order.price)

@app.delete("/api/arcade/{run_id}/orders/{order_id}")
def arcade_cancel(run_id: str, order_id: str):
    return cancel_order(run_id, order_id)

@app.post("/api/arcade/{run_id}/advance")
def arcade_advance(run_id: str, request: ArcadeAdvance):
    return advance_run(run_id, request.count, request.until_action)

@app.put("/api/arcade/{run_id}/strategy")
def arcade_strategy(run_id: str, strategy: ArcadeStrategy):
    return set_strategy(run_id, strategy.code)

class ArcadeRisk(BaseModel):
    stop_loss_pct: float = Field(default=0, ge=0, le=75)
    take_profit_pct: float = Field(default=0, ge=0, le=75)

@app.put("/api/arcade/{run_id}/risk")
def arcade_risk(run_id: str, risk: ArcadeRisk):
    return set_risk(run_id, risk.stop_loss_pct, risk.take_profit_pct)

@app.get("/api/instruments/discover")
def discover_instruments(search: str = Query(..., min_length=2, max_length=60)):
    return search_yahoo(search)

class ImportTicker(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)

@app.post("/api/instruments/import")
def add_instrument(request: ImportTicker):
    return import_yahoo(request.symbol)

# Multi-asset Arcade lives in a separate SQLite table, preserving older saves.
from . import portfolio_arcade as portfolio

class PortfolioSeasonStart(BaseModel):
    asset_ids: list[str] = Field(min_length=2, max_length=16)
    period: Literal["7D", "30D", "60D", "6M", "1Y", "2Y", "5Y", "10Y", "MAX"] = "5Y"
    resolution: Literal["1m", "5m", "15m", "1h", "1d"] = "1d"
    starting_point: float = Field(default=0.3, ge=0.15, le=0.75)
    start_date: str | None = Field(default=None, max_length=10)

class PortfolioOrder(BaseModel):
    asset_id: str
    side: Literal["buy", "sell"]
    kind: Literal["market", "limit", "stop"] = "market"
    size: str = Field(min_length=1, max_length=40)
    size_type: Literal["percent", "units"] = "percent"
    price: str | None = None

@app.get("/api/portfolio-seasons")
def portfolio_runs():
    return portfolio.list_seasons()

@app.post("/api/portfolio-seasons")
def portfolio_new(request: PortfolioSeasonStart):
    return portfolio.create_season(request.asset_ids, request.period,
                                    request.starting_point, request.start_date, request.resolution)

class TournamentReplayStart(BaseModel):
    strategy_id: str = Field(min_length=1, max_length=100)
    period: Literal["2Y", "5Y", "10Y", "MAX"] = "MAX"
    starting_point: float = Field(default=0.30, ge=0.15, le=0.75)
    start_date: str | None = Field(default=None, max_length=10)


@app.post("/api/portfolio-seasons/from-tournament")
def portfolio_from_tournament(body: TournamentReplayStart):
    from . import tournament_strategies
    # The private strategy lookup rejects public-demo access before loading data.
    tournament_strategies.get(body.strategy_id)
    return portfolio.create_tournament_season(
        body.strategy_id, body.period, body.starting_point, body.start_date)


@app.get("/api/portfolio-seasons/{run_id}")
def portfolio_get(run_id: str):
    return portfolio.get_season(run_id)

@app.post("/api/portfolio-seasons/{run_id}/advance")
def portfolio_step(run_id: str, request: ArcadeAdvance):
    return portfolio.advance(run_id, request.count, request.until_action)

@app.post("/api/portfolio-seasons/{run_id}/orders")
def portfolio_order(run_id: str, request: PortfolioOrder):
    return portfolio.order(run_id, request.asset_id, request.side,
                           request.kind, request.size, request.size_type, request.price)

@app.delete("/api/portfolio-seasons/{run_id}/orders/{order_id}")
def portfolio_cancel(run_id: str, order_id: str):
    return portfolio.cancel(run_id, order_id)

@app.put("/api/portfolio-seasons/{run_id}/strategy")
def portfolio_strategy(run_id: str, request: ArcadeStrategy):
    return portfolio.strategy(run_id, request.code)

@app.put("/api/portfolio-seasons/{run_id}/risk")
def portfolio_risk(run_id: str, request: ArcadeRisk):
    return portfolio.risk(run_id, request.stop_loss_pct, request.take_profit_pct)


@app.get("/api/arcade/{run_id}/at/{step}")
def arcade_historical_view(run_id: str, step: int):
    from .arcade import get_at
    return get_at(run_id, step)

@app.get("/api/portfolio-seasons/{run_id}/at/{step}")
def portfolio_historical_view(run_id: str, step: int):
    return portfolio.get_at(run_id, step)

@app.get("/api/portfolio-seasons/{run_id}/analytics")
def portfolio_analytics(run_id: str, at: int | None = Query(None, ge=0)):
    return portfolio.get_analysis(run_id, at)

@app.get("/api/arcade/{run_id}/analytics")
def arcade_analytics(run_id: str, at: int | None = Query(None, ge=0)):
    from .arcade import get_analysis
    return get_analysis(run_id, at)

# AI advisor is read-only. Proposals must pass the same DSL validator and
# are NEVER saved to a game or submitted as orders by this endpoint.
from .ai_assistant import advise as ai_advise, provider_status as ai_provider_status, warmup_ollama as ai_warmup_ollama, stream_advice as ai_stream_advice

class AITurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1000)

class AIQuestion(BaseModel):
    mode: Literal["single", "portfolio"]
    run_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=1200)
    history: list[AITurn] = Field(default_factory=list, max_length=6)
    language: Literal["en", "zh-CN"] = "en"
    model: str | None = Field(default=None, min_length=1, max_length=100)

@app.get("/api/ai/status")
def ai_status(model: str | None = Query(default=None, min_length=1, max_length=100)):
    return ai_provider_status(model)

@app.post("/api/ai/warmup")
def ai_warmup():
    return ai_warmup_ollama()

@app.post("/api/ai/ask")
def ai_ask(request: AIQuestion):
    return ai_advise(request.mode, request.run_id, request.question,
                     [turn.model_dump() for turn in request.history], request.language,
                     request.model)

@app.post("/api/ai/ask/stream")
def ai_ask_stream(body: AIQuestion):
    # The same private-bridge authentication middleware guards this route.
    # No model output is persisted or written to server logs. Only the
    # answer-field preview is streamed; the complete candidate strategy is
    # sent only after passing the existing DSL validator.
    from .ai_assistant import configuration
    if configuration()["provider"] != "llama_cpp":
        raise HTTPException(422, detail="Local llama.cpp streaming is not enabled.")
    output = ai_stream_advice(
        body.mode, body.run_id, body.question,
        [turn.model_dump() for turn in body.history], body.language, body.model)
    return StreamingResponse(output, media_type="text/event-stream", headers={
        "Cache-Control": "no-store",
        "X-Accel-Buffering": "no",
        "X-Content-Type-Options": "nosniff",
    })


# Stochastic research is computed exclusively from already-revealed bars.
class ScenarioRequest(BaseModel):
    mode: Literal["single", "portfolio"]
    run_id: str = Field(min_length=1, max_length=100)
    asset_id: str | None = Field(default=None, max_length=40)
    horizon: int = Field(default=20, ge=1, le=60)
    lookback: int = Field(default=60, ge=20, le=252)
    seed: int = Field(default=0, ge=0, le=2147483647)

@app.post("/api/research/scenarios")
def research_scenarios(request: ScenarioRequest):
    from .stochastic import forecast_for_game
    return forecast_for_game(request.mode, request.run_id, request.asset_id,
                             request.horizon, request.lookback, request.seed)

class BlackScholesRequest(BaseModel):
    spot: float = Field(gt=0, le=1e10)
    strike: float = Field(gt=0, le=1e10)
    maturity_years: float = Field(gt=0, le=30)
    volatility_annual: float = Field(ge=0, le=10)
    risk_free_rate: float = Field(default=.03, ge=-.5, le=1)
    dividend_yield: float = Field(default=0, ge=0, le=1)

@app.post("/api/research/black-scholes")
def research_option_pricing(request: BlackScholesRequest):
    from .stochastic import black_scholes
    return {
        **black_scholes(request.spot,request.strike,request.maturity_years,
                        request.volatility_annual,request.risk_free_rate,
                        request.dividend_yield),
        "method":"European Black-Scholes theoretical option value",
        "not_a_price_forecast": True,
    }

# Saved strategy versions are independent of live session strategy activation.
from . import strategy_library as saved_strategy_library

class SaveStrategyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    mode: Literal["single", "portfolio"]
    code: str = Field(min_length=1, max_length=1800)
    symbols: list[str] = Field(min_length=1, max_length=5)
    source_run_id: str | None = Field(default=None, max_length=100)

@app.get("/api/strategies")
def strategy_library_list(mode: Literal["single", "portfolio"] | None = None):
    return saved_strategy_library.list_saved(mode)

@app.post("/api/strategies")
def strategy_library_save(request: SaveStrategyRequest):
    return saved_strategy_library.store(request.mode,request.name,request.code,
        request.symbols,request.source_run_id)

@app.get("/api/strategies/{strategy_id}")
def strategy_library_get(strategy_id: str):
    return saved_strategy_library.get(strategy_id)

@app.delete("/api/strategies/{strategy_id}")
def strategy_library_delete(strategy_id: str):
    return saved_strategy_library.delete(strategy_id)
