"""Verify the opt-in tunnel demo cannot attach to local private storage or AI."""
import os
import subprocess
import sys
from pathlib import Path


def _probe(extra):
    root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env.update(extra)
    return subprocess.run(
        [sys.executable, "-c",
         "from backend.main import health; print(health())"],
        cwd=root, env=env, capture_output=True, text=True, timeout=15,
    )


def test_public_demo_refuses_missing_isolation_or_enabled_ai(tmp_path):
    demo = {
        "TRADING_SIM_PUBLIC_DEMO": "1",
        "TRADING_SIM_AI_PROVIDER": "off",
        "TRADING_SIM_ARCADE_DB": str(tmp_path / "arcade.sqlite3"),
        "TRADING_SIM_DB": str(tmp_path / "trading.sqlite3"),
        "TRADING_SIM_STRATEGY_DB": str(tmp_path / "strategy.sqlite3"),
        "TRADING_SIM_CUSTOM_INSTRUMENTS": str(tmp_path / "instruments.json"),
        "TRADING_SIM_MARKET_DIR": str(tmp_path / "market"),
    }
    successful = _probe(demo)
    assert successful.returncode == 0, successful.stderr
    assert "'mode': 'public-demo'" in successful.stdout
    assert not (tmp_path / "arcade.sqlite3").exists()

    missing = dict(demo)
    missing.pop("TRADING_SIM_STRATEGY_DB")
    refused = _probe(missing)
    assert refused.returncode != 0
    assert "isolated path" in refused.stderr

    enabled_ai = dict(demo, TRADING_SIM_AI_PROVIDER="ollama")
    refused = _probe(enabled_ai)
    assert refused.returncode != 0
    assert "cannot expose a local or paid AI provider" in refused.stderr

    private_data = Path(__file__).resolve().parents[2] / "data"
    unsafe = dict(demo, TRADING_SIM_DB=str(private_data / "trading.sqlite3"))
    refused = _probe(unsafe)
    assert refused.returncode != 0
    assert "outside private data" in refused.stderr


def test_normal_local_backend_remains_local():
    result = _probe({"TRADING_SIM_PUBLIC_DEMO": "0"})
    assert result.returncode == 0, result.stderr
    assert "'mode': 'local'" in result.stdout
