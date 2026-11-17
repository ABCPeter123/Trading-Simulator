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
    max_allocation_pct:float=Field(default=10,gt=0,le=25)
    max_realized_loss_pct:float=Field(default=5,ge=0.5,le=25)
    max_daily_signals:int=Field(default=4,ge=1,le=20)

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
