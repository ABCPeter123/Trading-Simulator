"""Offline synthetic checks for durable history bootstrap and reconciliation.

These tests cannot contact a live provider, place trades, or expose owner data.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend import archive, market_ingestion as ingest
from backend.main import app


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest, "DB_PATH", tmp_path / "queue.sqlite3")
    monkeypatch.setenv("TRADING_SIM_MARKET_DIR", str(tmp_path / "ohlcv"))
    monkeypatch.delenv("TRADING_SIM_PUBLIC_DEMO", raising=False)
    return tmp_path


def test_subscription_queues_initial_history_and_hourly_reconciliation(isolated):
    client = TestClient(app)
    response = client.post("/api/market-data/subscriptions",
                           json={"asset_id": "spy", "resolution": "5m"})
    assert response.status_code == 201
    assert response.json()["backfill_queued"] is True
    jobs = ingest.list_reconciliation_jobs()
    assert len(jobs) == 2
    assert {j["kind"] for j in jobs} == {"bootstrap", "reconcile"}
    health = client.get("/api/market-data/health").json()
    assert health["reconciliation_jobs"] == 2
    assert health["last_updates"][0]["bootstrap"]["status"] == "pending"
    assert health["last_updates"][0]["reconciliation"]["status"] == "pending"
    assert health["delivery_guaranteed"] is False


def test_failed_backfill_retries_without_claiming_success(isolated):
    ingest.subscribe("spy", "15m")
    now = datetime(2026, 11, 17, 14, 0, tzinfo=timezone.utc)
    calls = []
    def fail(asset_id, resolution, kind, instant):
        calls.append((asset_id, resolution, kind))
        raise ValueError("Synthetic missing data")
    initial = ingest.run_reconciliation_due(now, execute=fail)
    assert initial[0]["status"] == "retry_pending"
    assert initial[0]["error"] == "ValueError"
    assert len(calls) == 1
    bootstrap = next(j for j in ingest.list_reconciliation_jobs()
                     if j["kind"] == "bootstrap")
    assert bootstrap["last_success"] is None
    assert bootstrap["failures"] == 1
    assert bootstrap["due_at"] == (now + timedelta(minutes=1)).isoformat()
    assert ingest.run_reconciliation_due(now + timedelta(seconds=30), execute=fail) == []
    ingest.run_reconciliation_due(now + timedelta(seconds=61), execute=fail)
    bootstrap = next(j for j in ingest.list_reconciliation_jobs()
                     if j["kind"] == "bootstrap")
    assert bootstrap["failures"] == 2
    assert bootstrap["due_at"] == (now + timedelta(seconds=61+120)).isoformat()


def test_completed_bootstrap_does_not_redownload_and_reconcile_repeats_hourly(
    isolated
):
    ingest.subscribe("spy", "1d")
    now = datetime.now(timezone.utc) + timedelta(minutes=2)
    invoked = []
    def complete(asset_id, resolution, kind, instant):
        invoked.append(kind)
        return {"verified_bars": 14, "verified_through": int(now.timestamp())}
    ingest.run_reconciliation_due(now, execute=complete)
    assert invoked == ["bootstrap"]
    ingest.run_reconciliation_due(now + timedelta(seconds=1), execute=complete)
    assert invoked == ["bootstrap","reconcile"]
    assert ingest.run_reconciliation_due(now + timedelta(minutes=2),
                                         execute=complete) == []
    ingest.run_reconciliation_due(now + timedelta(hours=1, minutes=1),
                                  execute=complete)
    assert invoked == ["bootstrap","reconcile","reconcile"]
    assert next(j for j in ingest.list_reconciliation_jobs()
                if j["kind"] == "bootstrap")["failures"] == 0


def test_repair_checks_source_values_and_timestamp_uniqueness(isolated):
    now = 1731800000
    bar = {"time": now, "open": 101.0, "high": 104.0,
           "low": 99.0, "close": 102.0, "volume": 1000.0}
    identical = dict(bar)
    result = ingest._merge_verified("spy", "1d", [bar, identical], "MAX")
    assert result["verified_bars"] == 1
    stats = archive.archive_stats("spy", "MAX")
    assert stats["bars"] == 1

    bad = dict(bar, close=105.0, high=105.0)
    with pytest.raises(ValueError, match="Conflicting"):
        ingest._merge_verified("spy", "1d", [bar, bad], "MAX")
    assert archive.archive_stats("spy", "MAX")["bars"] == 1

    malformed = dict(bar, close=-1)
    with pytest.raises(ValueError, match="malformed"):
        ingest._merge_verified("spy", "1d", [malformed], "MAX")
    assert archive.archive_stats("spy", "MAX")["bars"] == 1


def test_reconciliation_does_not_run_for_disabled_or_public_demo(isolated, monkeypatch):
    ingest.subscribe("spy","1m")
    ingest.unsubscribe("spy","1m")
    assert ingest.run_reconciliation_due(datetime.now(timezone.utc)+timedelta(days=1))==[]
    assert ingest.list_reconciliation_jobs()==[]
    monkeypatch.setenv("TRADING_SIM_PUBLIC_DEMO","1")
    assert ingest.run_reconciliation_due()==[]


def test_existing_subscription_migrates_to_durable_queue(isolated):
    now=datetime.now(timezone.utc)+timedelta(minutes=2)
    ingest.subscribe("spy","1h")
    with ingest._db() as conn:
        conn.execute("DELETE FROM reconciliation_jobs")
        conn.commit()
    calls=[]
    def fake(asset,res,kind,stamp):
        calls.append((asset,res,kind))
        return {"verified_bars":1,"verified_through":int(now.timestamp())}
    ingest.run_reconciliation_due(now,execute=fake)
    assert calls==[("spy","1h","bootstrap")]
    assert len(ingest.list_reconciliation_jobs())==2
