"""Synthetic reproducibility tests for imported research exposure settings."""
import json

import pytest
from fastapi import HTTPException

from backend import tournament_strategies as strategy
from backend import portfolio_research as portfolio


def spec(**overrides):
    value={"version":1,"symbols":["spy","qqq","ief"],
           "model":"equal_weight","max_position_pct":40,
           "delay_sessions":1,"rebalance_sessions":21,
           "research_only":False,"restricted_research":False,
           "short_proxy_research":False}
    return {**value,**overrides}


def test_custom_long_only_exposure_fields_preserved_when_validated():
    user=spec(target_investment_pct=100,equity_class_cap_pct=100,
              redistribute_excess=True)
    checked=strategy.validate_spec(user)
    assert checked["target_investment_pct"]==100
    assert checked["equity_class_cap_pct"]==100
    assert checked["redistribute_excess"] is True
    assert strategy.validate_spec(spec())["model"]=="equal_weight"


@pytest.mark.parametrize("field,value",[
    ("target_investment_pct",101),
    ("equity_class_cap_pct",101),
    ("redistribute_excess","yes"),
    ("target_investment_pct",float("nan")),
])
def test_invalid_custom_exposures_rejected(field,value):
    with pytest.raises(HTTPException) as error:
        strategy.validate_spec(spec(**{field:value}))
    assert error.value.status_code==422


def test_advanced_models_cannot_silently_inherit_cash_exposure_overrides():
    advanced=spec(model="leveraged_trend",version=2,research_only=True,
                  target_investment_pct=100)
    with pytest.raises(HTTPException) as error:
        strategy.validate_spec(advanced)
    assert error.value.status_code==422


def test_import_carries_high_performance_settings_into_private_version(tmp_path,monkeypatch):
    monkeypatch.setattr(strategy,"DB_PATH",tmp_path/"versions.sqlite3")
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO",raising=False)
    job={
        "status":"completed",
        "params":{"max_position_pct":40,"delay_sessions":1,
                  "research_objective":"high_performance",
                  "target_investment_pct":100,
                  "equity_class_cap_pct":100,"redistribute_excess":True},
        "result":{"top10":[{
            "rank":1,"basket_type":"synthetic_diversified",
            "symbols":["spy","qqq","ief"],"model":"equal_weight",
            "restricted_research":False,"short_proxy_research":False,
            "research_only":False}]},
    }
    monkeypatch.setattr(strategy.universe_research,"get_job",lambda uid:job)
    imported=strategy.import_rank("fixture-only",1)
    loaded=strategy.get(imported["id"])
    encoded=json.loads(loaded["code"])
    assert encoded["target_investment_pct"]==100
    assert encoded["equity_class_cap_pct"]==100
    assert encoded["redistribute_excess"] is True
    assert loaded["model"]=="equal_weight"
    # Standard research algorithm uses those exact values when replay calls it.
    prices={"spy":[100.]*200,"qqq":[100.]*200,"ief":[100.]*200}
    metadata={s:{"group":"bond" if s=="ief" else "equity"} for s in prices}
    weights=portfolio._weights("equal_weight",list(prices),prices,180,metadata,.40,
                               gross_target=encoded["target_investment_pct"]/100,
                               equity_cap=encoded["equity_class_cap_pct"]/100,
                               redistribute=encoded["redistribute_excess"])
    assert sum(weights.values())==pytest.approx(1.)


def test_ui_cannot_offer_live_deployment_for_unreproducible_research_overrides():
    from pathlib import Path
    root=Path(__file__).resolve().parents[2]
    live=(root/"backend"/"live_machine.py").read_text(encoding="utf-8")
    replay=(root/"backend"/"portfolio_arcade.py").read_text(encoding="utf-8")
    frontend=(root/"src"/"UniverseResearch.tsx").read_text(encoding="utf-8")
    assert "Custom research exposure controls are not yet supported in live monitoring" in live
    assert 'gross_target=float(config.get("target_investment_pct",95.))/100' in replay
    assert "customResearchExposure" in frontend
    assert "Live engine unavailable for custom research exposure" in frontend
