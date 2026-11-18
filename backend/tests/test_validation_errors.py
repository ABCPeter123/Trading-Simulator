"""Synthetic regression: API validation must explain 422 without echoing inputs."""
from fastapi.testclient import TestClient

from backend.main import app


def test_research_422_explains_field_and_bounds():
    response = TestClient(app).post("/api/live/research/universe/jobs", json={
        "scope": "all", "delay_sessions": 1,
        "max_drawdown_pct": 99, "max_position_pct": 35,
    })
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "max_drawdown_pct" in detail
    assert "60" in detail


def test_invalid_string_is_not_reflected_in_validation_errors():
    private_marker = "DO_NOT_ECHO_PRIVATE_VALUE"
    response = TestClient(app).post("/api/live/research/universe/jobs", json={
        "scope": private_marker, "delay_sessions": 1,
        "max_drawdown_pct": 30, "max_position_pct": 35,
    })
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert "scope" in detail
    assert private_marker not in detail
    assert "supported choices" in detail
