"""Regression tests for the renamed Vercel Global Config REST endpoint.

No external Vercel API calls. All tokens and addresses are fake test fixtures.
"""
import importlib.util
import io
import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

SCRIPT=Path(__file__).resolve().parents[2]/"scripts/publish_tunnel.py"
spec=importlib.util.spec_from_file_location("test_tunnel_publisher",SCRIPT)
publisher=importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)

FAKE_URL="https://synthetic-fixture.trycloudflare.com"
FAKE_TOKEN="fictional-vercel-token-for-tests"

def test_publish_calls_current_global_config_endpoint(tmp_path,monkeypatch,capsys):
    monkeypatch.delenv("TRADING_SIM_VERCEL_TOKEN",raising=False)
    token_path=tmp_path/"vercel-token.txt"
    token_path.write_text(FAKE_TOKEN)
    monkeypatch.setattr(publisher,"TOKEN_FILE",token_path)
    observed={}
    class Response:
        status=204
        def __enter__(self):return self
        def __exit__(self,*args):return False
    def fake_request(request,timeout):
        observed.update({
          "url":request.full_url,
          "method":request.get_method(),
          "auth":request.get_header("Authorization"),
          "body":json.loads(request.data),
          "timeout":timeout,
        })
        return Response()
    monkeypatch.setattr(publisher,"urlopen",fake_request)
    publisher.publish(FAKE_URL)
    assert observed["method"]=="PATCH"
    assert observed["url"]==(
      f"https://api.vercel.com/v1/global-config/{publisher.CONFIG_ID}/items?"
      f"teamId={publisher.TEAM_ID}"
    )
    assert observed["auth"]=="Bearer "+FAKE_TOKEN
    assert observed["body"]=={"items":[{
      "operation":"upsert","key":"bridge","value":{"url":FAKE_URL},
    }]}
    out=capsys.readouterr().out
    assert "updated" in out
    assert FAKE_TOKEN not in out

@pytest.mark.parametrize("status,expected",[
    (400,"rejected"),(401,"rejected the local access token"),(403,"TEAM"),(404,"not found"),
    (429,"rate limited"),
])
def test_publisher_reports_status_without_leaking_auth(tmp_path,monkeypatch,status,expected):
    monkeypatch.setenv("TRADING_SIM_VERCEL_TOKEN",FAKE_TOKEN)
    def fail(request,timeout):
        raise HTTPError(request.full_url,status,"Sensitive header text",{},io.BytesIO(FAKE_TOKEN.encode()))
    monkeypatch.setattr(publisher,"urlopen",fail)
    with pytest.raises(RuntimeError) as exc:
        publisher.publish(FAKE_URL)
    msg=str(exc.value)
    assert f"HTTP {status}" in msg
    assert expected.lower() in msg.lower()
    assert FAKE_TOKEN not in msg
    assert FAKE_URL not in msg

def test_publisher_rejects_invalid_external_url(tmp_path,monkeypatch):
    monkeypatch.setenv("TRADING_SIM_VERCEL_TOKEN",FAKE_TOKEN)
    monkeypatch.setattr(publisher,"urlopen",
      lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError("No network allowed")))
    with pytest.raises(ValueError):
        publisher.publish("https://other-site.example")
    with pytest.raises(ValueError):
        publisher.publish(FAKE_URL+"/api/private")

def test_publisher_network_error_is_safe(monkeypatch):
    monkeypatch.setenv("TRADING_SIM_VERCEL_TOKEN",FAKE_TOKEN)
    monkeypatch.setattr(publisher,"urlopen",
      lambda req,timeout: (_ for _ in ()).throw(URLError(FAKE_TOKEN)))
    with pytest.raises(RuntimeError) as exc:
        publisher.publish(FAKE_URL)
    assert FAKE_TOKEN not in str(exc.value)
    assert "connectivity" in str(exc.value)

def test_command_line_records_safe_http_reason(tmp_path,monkeypatch,capsys):
    status_path=tmp_path/"publish-status.txt"
    monkeypatch.setenv("TRADING_SIM_PUBLISH_STATUS_PATH",str(status_path))
    monkeypatch.setenv("TRADING_SIM_VERCEL_TOKEN",FAKE_TOKEN)
    def fail(request,timeout):
        raise HTTPError(request.full_url,403,"confidential response",{},
                        io.BytesIO(FAKE_TOKEN.encode()))
    monkeypatch.setattr(publisher,"urlopen",fail)
    code=publisher.main([FAKE_URL])
    assert code==1
    stored=status_path.read_text(encoding="utf-8")
    assert "HTTP 403" in stored
    assert "Global Config" in stored
    assert FAKE_TOKEN not in stored
    assert FAKE_URL not in stored
    streams=capsys.readouterr()
    assert FAKE_TOKEN not in streams.err
    assert "HTTP 403" in streams.err

def test_command_line_records_unexpected_runtime_type_without_secrets(tmp_path,monkeypatch):
    status_path=tmp_path/"publish-status.txt"
    monkeypatch.setenv("TRADING_SIM_PUBLISH_STATUS_PATH",str(status_path))
    def fail(url):
        raise OSError("contains secret private-local-token")
    monkeypatch.setattr(publisher,"publish",fail)
    assert publisher.main([FAKE_URL])==1
    stored=status_path.read_text(encoding="utf-8")
    assert "OSError" in stored
    assert "private-local-token" not in stored

def test_command_line_success_status(tmp_path,monkeypatch):
    status_path=tmp_path/"publish-status.txt"
    monkeypatch.setenv("TRADING_SIM_PUBLISH_STATUS_PATH",str(status_path))
    monkeypatch.setattr(publisher,"publish",lambda url:None)
    assert publisher.main([FAKE_URL])==0
    assert status_path.read_text(encoding="utf-8").strip()=="OK"

def test_local_publishing_token_takes_precedence_over_inherited_env(tmp_path,monkeypatch):
    token_file=tmp_path/"vercel-token.txt"
    token_file.write_text("synthetic-valid-file-token",encoding="utf-8")
    monkeypatch.setattr(publisher,"TOKEN_FILE",token_file)
    monkeypatch.setenv("TRADING_SIM_VERCEL_TOKEN","synthetic-wrong-env-token")
    captured={}
    class Response:
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):return False
    def publish_request(req,timeout):
        captured["auth"]=req.get_header("Authorization")
        return Response()
    monkeypatch.setattr(publisher,"urlopen",publish_request)
    publisher.publish(FAKE_URL)
    assert captured["auth"]=="Bearer synthetic-valid-file-token"
