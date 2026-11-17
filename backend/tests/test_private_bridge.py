"""Offline integration checks for the opt-in private Vercel frontend bridge."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST_ORIGIN = "https://trading-example.vercel.app"
TOKEN = "x" * 64

def probe(changes, script):
    env = os.environ.copy()
    env.update({
        "TRADING_SIM_PUBLIC_DEMO": "0",
        "TRADING_SIM_PRIVATE_BRIDGE": "1",
        "TRADING_SIM_ALLOWED_ORIGINS": TEST_ORIGIN,
        "TRADING_SIM_PRIVATE_API_TOKEN": TOKEN,
    })
    env.update(changes)
    return subprocess.run([sys.executable, "-c", script], cwd=ROOT,
                          env=env, capture_output=True, text=True, timeout=15)

def test_private_bridge_authentication_cors_and_isolation():
    script = """
from fastapi.testclient import TestClient
from backend.main import app
c=TestClient(app)
origin='https://trading-example.vercel.app'
token='Bearer ' + 'x'*64
r=c.get('/api/health')
assert r.status_code==401, r.text
r=c.get('/api/health',headers={'Authorization':'Bearer wrong','Origin':origin})
assert r.status_code==401, r.text
assert r.headers.get('access-control-allow-origin')==origin
assert r.headers.get('cache-control')=='no-store'
r=c.get('/api/health',headers={'Authorization':token,'Origin':'https://attacker.example'})
assert r.status_code==403, r.text
r=c.get('/api/health',headers={'Authorization':token,'Origin':origin})
assert r.status_code==200, r.text
assert r.json()['mode']=='private-bridge'
assert r.headers.get('access-control-allow-origin')==origin
assert r.headers.get('cache-control')=='no-store'
r=c.options('/api/health',headers={
 'Origin':origin,'Access-Control-Request-Method':'GET',
 'Access-Control-Request-Headers':'authorization',
 'Access-Control-Request-Private-Network':'true'})
assert r.status_code==200, r.text
assert r.headers.get('access-control-allow-origin')==origin
assert r.headers.get('access-control-allow-private-network')=='true'
print('private bridge authenticated and isolated')
"""
    result = probe({}, script)
    assert result.returncode == 0, result.stderr
    assert "private bridge authenticated and isolated" in result.stdout

def test_private_bridge_fail_closed_without_token_or_valid_origin():
    script = "import backend.main"
    for invalid in [
        {"TRADING_SIM_PRIVATE_API_TOKEN": ""},
        {"TRADING_SIM_PRIVATE_API_TOKEN": "short"},
        {"TRADING_SIM_ALLOWED_ORIGINS": ""},
        {"TRADING_SIM_ALLOWED_ORIGINS": "http://trading-example.vercel.app"},
        {"TRADING_SIM_ALLOWED_ORIGINS": "https://trading-example.vercel.app/something"},
        {"TRADING_SIM_PUBLIC_DEMO": "1"},
    ]:
        result = probe(invalid, script)
        assert result.returncode != 0, f"Unsafe private bridge started: {invalid.keys()}"
        assert "RuntimeError" in result.stderr

def test_local_api_is_password_free_only_without_private_bridge():
    # Localhost Vite uses a separate FastAPI process; an inherited bridge
    # password verifier must not silently turn it into a cloud-only service.
    script = """
from fastapi.testclient import TestClient
from backend.main import app
c=TestClient(app)
r=c.get('/api/health')
assert r.status_code==200, r.text
assert r.json()['mode']=='local'
assert c.get('/api/live/research/portfolio/jobs').status_code==200
assert c.post('/api/auth/login',json={'password':'fixture'}).status_code==404
print('local api requires no cloud password')
"""
    result = probe({"TRADING_SIM_PRIVATE_BRIDGE":"0",
                    "TRADING_SIM_PRIVATE_PASSWORD_HASH":"fixture-not-used"}, script)
    assert result.returncode==0, result.stderr
    assert "local api requires no cloud password" in result.stdout
