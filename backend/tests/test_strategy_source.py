"""Offline regression for genuine engine source display, using only fictional specs."""
from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import advanced_portfolio_research as advanced
from backend import portfolio_research as portfolio
from backend import strategy_source
from backend import tournament_strategies
from backend import main


@pytest.fixture
def synthetic_spec(monkeypatch):
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO", raising=False)
    return {
        "version": 1,
        "model": "equal_weight",
        "symbols": ["synthetic_alpha", "synthetic_beta"],
        "max_position_pct": 35,
        "delay_sessions": 1,
        "rebalance_sessions": 21,
        "research_only": False,
    }


def test_actual_python_allocation_and_fill_source_not_pseudocode(synthetic_spec):
    detail = strategy_source.source_for_model(synthetic_spec)
    assert detail["runtime"] == "Python 3"
    assert detail["executable"] is True
    assert detail["entry_point"] == "backend.portfolio_research._weights"
    assert detail["research_execution_entry_point"] == "backend.portfolio_research._segment"
    assert detail["sections"][0]["code"] == inspect.getsource(portfolio._weights)
    assert detail["sections"][1]["code"] == inspect.getsource(portfolio._segment)
    assert any(s["code"] == inspect.getsource(portfolio._vol) for s in detail["sections"])
    for module in detail["files"]:
        original = (strategy_source.ROOT / module["path"]).read_bytes()
        assert module["code"].encode("utf-8") == original
        assert module["sha256"] == hashlib.sha256(original).hexdigest()
        assert module["path"].startswith("backend/")
    # The response contains generic engine implementation, not the private strategy spec.
    assert "synthetic_alpha" not in repr(detail)
    assert "synthetic_beta" not in repr(detail)


@pytest.mark.parametrize("model", advanced.MODELS)
def test_advanced_model_uses_actual_signed_position_engine(model, synthetic_spec):
    spec = {
        **synthetic_spec, "model": model, "version": 2,
        "research_only": model in advanced.RESEARCH_ONLY,
    }
    detail = strategy_source.source_for_model(spec)
    assert detail["entry_point"] == "backend.advanced_portfolio_research.weights"
    assert detail["research_execution_entry_point"] == "backend.advanced_portfolio_research.segment"
    assert detail["sections"][0]["code"] == inspect.getsource(advanced.weights)
    assert detail["sections"][1]["code"] == inspect.getsource(advanced.segment)
    assert any(f["path"] == "backend/portfolio_research.py" for f in detail["files"])


@pytest.mark.parametrize("context,expected", [
    ("research", "Tournament runner and scoring (active Python function)"),
    ("simulation", "Replay model rebalance (active Python function)"),
    ("live", "Live portfolio recommendation logic (active Python function)"),
])
def test_context_includes_actual_execution_path(synthetic_spec, context, expected):
    detail = strategy_source.source_for_model(synthetic_spec, context)
    assert detail["context"] == context
    assert expected in [section["label"] for section in detail["sections"]]


def test_private_http_endpoint_and_validation(synthetic_spec, monkeypatch):
    client = TestClient(main.app)
    endpoint = "/api/live/research/universe/strategy-source"
    response = client.post(endpoint, json={"spec": synthetic_spec, "context": "research"})
    assert response.status_code == 200, response.text
    assert response.json()["sections"][0]["function"] == "_weights"

    incorrect = {**synthetic_spec, "model": "made_up_model"}
    response = client.post(endpoint, json={"spec": incorrect})
    assert response.status_code == 422

    monkeypatch.setattr(main, "PUBLIC_DEMO", True)
    response = client.post(endpoint, json={"spec": synthetic_spec})
    assert response.status_code == 403
