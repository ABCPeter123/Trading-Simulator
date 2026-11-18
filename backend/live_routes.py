"""Owner-only live strategy operations API. All brokerage fills require human entry."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import live_machine as engine
from . import live_notifications
from . import research_optimizer
from . import portfolio_research
from . import research_queue
from . import universe_research
from . import tournament_strategies
from . import strategy_source
from . import strategy_period_queue
from . import walkforward_queue

router=APIRouter(prefix="/api/live", tags=["Private strategy machine"])

# Public demo never sees or creates the owner's live machine database.
def private():
    from .main import PUBLIC_DEMO
    if PUBLIC_DEMO:
        raise HTTPException(403, detail="Live strategy and actual trade records are private. Not available in demo mode.")

class DeployBody(BaseModel):
    strategy_id:str=Field(min_length=1,max_length=100)
    state:Literal["paper","live-monitor"]="paper"
    capital:float=Field(default=100000,ge=100,le=1e10)
    max_allocation_pct:float=Field(default=10,gt=0,le=50)
    max_realized_loss_pct:float=Field(default=5,ge=0.5,le=25)
    max_daily_signals:int=Field(default=4,ge=1,le=20)
    resolution:Literal["1d","1h","15m"]="1d"

class StateBody(BaseModel):
    state:Literal["paper","live-monitor","paused","retired"]

class SignalBody(BaseModel):
    status:Literal["acknowledged","skipped","expired"]

class AlertBody(BaseModel):
    status:Literal["acknowledged","resolved"]

class FillBody(BaseModel):
    signal_id:str|None=Field(default=None,max_length=100)
    asset_id:str=Field(min_length=1,max_length=32,pattern=r"^[A-Za-z0-9._-]+$")
    side:Literal["buy","sell"]
    quantity:float=Field(gt=0,le=1e10)
    price:float=Field(gt=0,le=1e10)
    fee:float=Field(default=0,ge=0,le=1e9)
    currency:Literal["USD","CAD","EUR","GBP"]="USD"
    executed_at:datetime
    broker_ref:str|None=Field(default=None,max_length=120)
    notes:str=Field(default="",max_length=2000)

class FillUpdate(BaseModel):
    asset_id:str|None=Field(default=None,max_length=32,pattern=r"^[A-Za-z0-9._-]+$")
    side:Literal["buy","sell"]|None=None
    quantity:float|None=Field(default=None,gt=0,le=1e10)
    price:float|None=Field(default=None,gt=0,le=1e10)
    fee:float|None=Field(default=None,ge=0,le=1e9)
    currency:Literal["USD","CAD","EUR","GBP"]|None=None
    executed_at:datetime|None=None
    broker_ref:str|None=Field(default=None,max_length=120)
    notes:str|None=Field(default=None,max_length=2000)

@router.get("/status")
def status():
    private()
    return engine.status()

@router.get("/deployments")
def deployments():
    private()
    return engine.deployments()

@router.post("/deployments")
def deploy(body:DeployBody):
    private()
    return engine.deploy(**body.model_dump())

@router.get("/deployments/{deployment_id}/strategy")
def deployment_strategy_source(deployment_id:str):
    private()
    return engine.get_deployment_source(deployment_id)


@router.put("/deployments/{deployment_id}")
def change_deployment(deployment_id:str,body:StateBody):
    private()
    return engine.change_state(deployment_id,body.state)

@router.post("/evaluate")
def evaluate():
    private()
    return engine.run_once()

@router.get("/signals")
def signals(status:str|None=None):
    private()
    if status is not None and status not in ("pending","acknowledged","filled","skipped","expired"):
        raise HTTPException(422,detail="Invalid signal filter.")
    return engine.signals(status)

@router.put("/signals/{signal_id}")
def signal_state(signal_id:str,body:SignalBody):
    private()
    return engine.update_signal(signal_id,body.status)

@router.get("/journal")
def journal():
    private()
    return engine.journal()

@router.post("/journal")
def add_fill(body:FillBody):
    private()
    return engine.record_fill(body.model_dump(mode="json"))

@router.put("/journal/{fill_id}")
def edit_fill(fill_id:str,body:FillUpdate):
    private()
    updates=body.model_dump(mode="json",exclude_unset=True)
    if not updates or any(v is None for k,v in updates.items() if k not in ("broker_ref",)):
        raise HTTPException(422,detail="Provide valid fields to edit.")
    return engine.edit_fill(fill_id,updates)

@router.get("/journal/{fill_id}/revisions")
def revisions(fill_id:str):
    private()
    return engine.fill_history(fill_id)

@router.get("/alerts")
def alerts():
    private()
    return engine.alerts()

@router.put("/alerts/{alert_id}")
def acknowledge_alert(alert_id:str,body:AlertBody):
    private()
    return engine.acknowledge_alert(alert_id,body.status)

@router.get("/notifications")
def notifications():
    private()
    return live_notifications.delivery_status()


class OptimizeRequest(BaseModel):
    asset_id:str=Field(min_length=1,max_length=32,pattern=r"^[A-Za-z0-9._-]+$")
    max_drawdown_pct:float=Field(default=15,ge=1,le=50)
    allocation_pct:float=Field(default=20,ge=1,le=25)

class NameRequest(BaseModel):
    name:str=Field(min_length=1,max_length=80)

@router.post("/research/optimize")
def optimize(body:OptimizeRequest):
    private()
    return research_optimizer.optimize(**body.model_dump())

@router.get("/research/runs")
def research_runs():
    private()
    return research_optimizer.list_runs()

@router.get("/research/runs/{run_id}")
def research_run(run_id:str):
    private()
    return research_optimizer.load_run(run_id)

@router.post("/research/runs/{run_id}/save")
def save_selected(run_id:str,body:NameRequest):
    private()
    return research_optimizer.save_selected(run_id,body.name)


class PortfolioCompareBody(BaseModel):
    symbols:list[str]=Field(min_length=2,max_length=16)
    max_drawdown_pct:float=Field(default=25,ge=1,le=50)
    max_position_pct:float=Field(default=35,ge=5,le=50)


@router.post("/research/portfolio/compare")
def compare_portfolios(body:PortfolioCompareBody):
    private()
    return portfolio_research.compare(**body.model_dump())


@router.get("/research/portfolio/runs")
def portfolio_research_runs():
    private()
    return portfolio_research.list_runs()


@router.get("/research/portfolio/runs/{run_id}")
def portfolio_research_run(run_id:str):
    private()
    return portfolio_research.load_run(run_id)


# Research queue is the website-first workflow. Requests only persist a job
# configuration on the password-protected Windows backend. The local worker
# computes independently of the browser and writes private full results.
@router.post("/research/portfolio/jobs",status_code=202)
def queue_portfolio_study(body:PortfolioCompareBody):
    private()
    return research_queue.enqueue(**body.model_dump())


@router.get("/research/portfolio/jobs")
def portfolio_jobs():
    private()
    return research_queue.list_jobs()


@router.get("/research/portfolio/jobs/{job_id}")
def portfolio_job(job_id:str):
    private()
    return research_queue.get_job(job_id)


@router.post("/research/portfolio/jobs/{job_id}/cancel")
def cancel_portfolio_job(job_id:str):
    private()
    return research_queue.cancel(job_id)


class UniverseStudyBody(BaseModel):
    scope:Literal["all","etfs","stocks"]="all"
    delay_sessions:Literal[1,2]=1
    max_drawdown_pct:float=Field(default=30,ge=5,le=60)
    max_position_pct:float=Field(default=35,ge=10,le=50)
    research_objective:Literal["balanced","high_performance"]="balanced"
    target_cagr_pct:float=Field(default=55,ge=10,le=100)
    target_sharpe:float=Field(default=2,ge=0.5,le=5)
    risk_free_pct:float=Field(default=3,ge=0,le=15)
    target_investment_pct:float=Field(default=95,ge=5,le=100)
    equity_class_cap_pct:float=Field(default=70,ge=10,le=100)
    redistribute_excess:bool=False


class TournamentSourceBody(BaseModel):
    spec: dict
    context: Literal["research", "simulation", "live"] = "research"


@router.post("/research/universe/strategy-source")
def tournament_strategy_source(body: TournamentSourceBody):
    private()
    return strategy_source.source_for_model(body.spec, body.context)


class StrategyPeriodBody(BaseModel):
    spec: dict
    start_date: str | None = Field(default=None,max_length=10)
    end_date: str | None = Field(default=None,max_length=10)
    max_position_pct: float | None = Field(default=None,ge=10,le=50)
    delay_sessions: Literal[1,2] | None = None
    slippage_bps: float = Field(default=8,ge=0,le=100)
    target_investment_pct: float | None = Field(default=None,ge=5,le=100)
    equity_class_cap_pct: float | None = Field(default=None,ge=10,le=100)
    redistribute_excess: bool | None = None


@router.post("/research/strategy-period/jobs",status_code=202)
def create_strategy_period_study(body:StrategyPeriodBody):
    private()
    return strategy_period_queue.enqueue(body.model_dump(exclude_none=True))


@router.get("/research/strategy-period/jobs/{job_id}")
def get_strategy_period_study(job_id:str):
    private()
    return strategy_period_queue.get_job(job_id)


@router.post("/research/strategy-period/jobs/{job_id}/cancel")
def cancel_strategy_period_study(job_id:str):
    private()
    return strategy_period_queue.cancel(job_id)


class WalkForwardBody(BaseModel):
    spec:dict
    search_width:Literal["focused","extended"]="focused"
    target_cagr_pct:float=Field(default=55,ge=10,le=100)
    target_sharpe:float=Field(default=2,ge=.5,le=5)
    risk_free_pct:float=Field(default=3,ge=0,le=15)
    max_drawdown_pct:float=Field(default=30,ge=5,le=60)
    slippage_bps:float=Field(default=8,ge=0,le=100)


@router.post("/research/walkforward/jobs",status_code=202)
def create_walkforward_study(body:WalkForwardBody):
    private()
    return walkforward_queue.enqueue(body.model_dump())


@router.get("/research/walkforward/jobs")
def list_walkforward_studies():
    private()
    return walkforward_queue.list_jobs()


@router.get("/research/walkforward/jobs/{job_id}")
def get_walkforward_study(job_id:str):
    private()
    return walkforward_queue.get_job(job_id)


@router.post("/research/walkforward/jobs/{job_id}/cancel")
def cancel_walkforward_study(job_id:str):
    private()
    return walkforward_queue.cancel(job_id)


@router.get("/research/universe/strategies")
def imported_tournament_strategies():
    private()
    return tournament_strategies.list_saved()


@router.post("/research/universe/jobs/{job_id}/strategies/{rank}",status_code=201)
def import_tournament_strategy(job_id:str, rank:int):
    private()
    return tournament_strategies.import_rank(job_id, rank)


@router.post("/research/universe/jobs",status_code=202)
def queue_universe_study(body:UniverseStudyBody):
    private()
    return universe_research.enqueue(**body.model_dump())


@router.get("/research/universe/jobs")
def universe_studies():
    private()
    return universe_research.list_jobs()


@router.get("/research/universe/jobs/{job_id}")
def universe_study(job_id:str):
    private()
    return universe_research.get_job(job_id)


@router.post("/research/universe/jobs/{job_id}/cancel")
def cancel_universe_study(job_id:str):
    private()
    return universe_research.cancel(job_id)

