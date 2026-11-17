"""Password-only private bridge security contract. Synthetic credentials only."""
import os
import subprocess
import sys
from pathlib import Path

from backend.bridge_password import hash_password, verify
from backend import bridge_password as password

ROOT=Path(__file__).resolve().parents[2]
PHRASE="fixture-only-fictitious-password"

def test_password_hash_uses_salt_and_not_plaintext():
    a=hash_password(PHRASE)
    b=hash_password(PHRASE)
    assert a!=b and PHRASE not in a
    assert verify(PHRASE,a)
    assert not verify("something else",a)

def test_password_session_expiration_revocation_and_throttle(monkeypatch):
    local_hash=hash_password(PHRASE)
    with password._LOCK:
        password._SESSIONS.clear()
        password._FAILS.clear()
        password._GLOBAL_FAILS.clear()
    assert password.new_session("wrong",local_hash,"synthetic-ip") is None
    token=password.new_session(PHRASE,local_hash,"synthetic-ip")
    assert token is not None
    assert password.authenticated("Bearer "+token)
    password.revoke("Bearer "+token)
    assert not password.authenticated("Bearer "+token)
    for _ in range(5):
        assert password.new_session("wrong",local_hash,"other-fixture-ip") is None
    assert password.new_session(PHRASE,local_hash,"other-fixture-ip") is None

def test_private_password_mode_denies_anonymous_api_and_rejects_wrong_password():
    env=os.environ.copy()
    env.update({"TRADING_SIM_PUBLIC_DEMO":"0","TRADING_SIM_PRIVATE_BRIDGE":"1",
                "TRADING_SIM_PRIVATE_PASSWORD_HASH":hash_password(PHRASE),
                "TRADING_SIM_PRIVATE_API_TOKEN":"",
                "TRADING_SIM_ALLOWED_ORIGINS":"https://trading-simulator-pp-48b0.vercel.app"})
    program="""
from fastapi.testclient import TestClient
from backend.main import app
c=TestClient(app)
origin='https://trading-simulator-pp-48b0.vercel.app'
assert c.get('/api/health').status_code==401
assert c.get('/api/auth/status').json()['login']=='password'
assert c.get('/api/live/status').status_code==401
bad=c.post('/api/auth/login',json={'password':'wrong'},headers={'Origin':origin})
assert bad.status_code==401 and bad.headers.get('access-control-allow-origin')==origin
blocked=c.post('/api/auth/login',json={'password':'fixture-only-fictitious-password'},
  headers={'Origin':'https://attacker.example'})
assert blocked.status_code==403
ok=c.post('/api/auth/login',json={'password':'fixture-only-fictitious-password'},
  headers={'Origin':origin})
assert ok.status_code==200,ok.text
token=ok.json()['token']
assert len(token)>50 and token!='fixture-only-fictitious-password'
assert c.get('/api/health',headers={'Authorization':'Bearer '+token}).status_code==200
assert c.get('/api/live/status',headers={'Authorization':'Bearer '+token}).status_code==200
assert c.post('/api/auth/logout',headers={'Authorization':'Bearer '+token}).status_code==200
assert c.get('/api/health',headers={'Authorization':'Bearer '+token}).status_code==401
print('password-only flow passed')
"""
    result=subprocess.run([sys.executable,"-c",program],cwd=ROOT,env=env,
                          capture_output=True,text=True,timeout=35)
    assert result.returncode==0,result.stderr
    assert "password-only flow passed" in result.stdout
