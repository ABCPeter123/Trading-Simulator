"""Publish ONLY ephemeral tunnel location to Vercel Global Config.

Owner-only script: requires a Vercel access token stored in Git-ignored
.local-state/private-bridge/vercel-token.txt. No password or trading data
is transmitted. No redeployment or paid hosted database is needed.
"""
from __future__ import annotations
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

TEAM_ID="team_elvyiHWjiraAZdyCWdNiuzpA"
CONFIG_ID="ecfg_5rfeza6sw9tnu0rikwgu0ugv46qt"
ROOT=Path(__file__).resolve().parents[1]
TOKEN_FILE=ROOT/".local-state"/"private-bridge"/"vercel-token.txt"
STATUS_FILE=ROOT/".local-state"/"private-bridge"/"publish-status.txt"
TUNNEL=re.compile(r"^https://[a-z0-9-]+\.trycloudflare\.com$")

def publish(url:str):
    if not TUNNEL.fullmatch(url):
        raise ValueError("Expected a Cloudflare Quick Tunnel HTTPS origin.")
    # The launcher saves an explicit, user-approved publishing token locally.
    # Prefer it over an unrelated inherited TRADING_SIM_VERCEL_TOKEN value.
    if TOKEN_FILE.exists():
        token=TOKEN_FILE.read_text(encoding="utf-8").strip()
        print("[publisher] Using locally saved Vercel publishing credential.")
    else:
        token=os.environ.get("TRADING_SIM_VERCEL_TOKEN","").strip()
        if token:
            print("[publisher] Using Vercel publishing credential from environment.")
    if not token or any(c.isspace() for c in token):
        raise ValueError("Vercel access token missing from local private-bridge setup.")
    payload=json.dumps({"items":[{
        "operation":"upsert","key":"bridge","value":{"url":url}
    }]}).encode("utf-8")
    # Vercel renamed /v1/edge-config to /v1/global-config in 2026.
    # Always target the team that owns the Global Config resource.
    endpoint="https://api.vercel.com/v1/global-config/"+CONFIG_ID+"/items?"+urlencode({"teamId":TEAM_ID})
    req=Request(endpoint,data=payload,method="PATCH",headers={
        "Authorization":"Bearer "+token,"Content-Type":"application/json"})
    try:
        with urlopen(req,timeout=15) as resp:
            if resp.status not in (200,201,204):
                raise RuntimeError("Vercel directory returned unexpected success status.")
    except HTTPError as exc:
        # Status codes are safe to report. Never display request headers,
        # token values, full HTTP exception objects, or provider response body.
        diagnostic={
            400:"Vercel rejected the directory update request.",
            401:"Vercel rejected the local access token. Check expiration or reset it with -ResetVercelToken.",
            403:"Vercel token cannot write this team's Global Config. Use a token scoped to the owning team, with Global Config write access.",
            404:"Vercel Global Config not found under this team. Confirm the directory and API endpoint are current.",
            409:"Vercel Global Config update conflicted; retry the launcher.",
            429:"Vercel rate limited the directory update; retry later.",
        }.get(exc.code,"Vercel Global Config request failed.")
        raise RuntimeError(f"{diagnostic} (HTTP {exc.code})") from None
    except URLError:
        raise RuntimeError("Cannot reach Vercel Global Config API. Check DNS and Internet connectivity.") from None
    print("Private engine address updated. Visitors only need the shared web password.")

def _save_status(message:str):
    """Store only a previously constructed, credential-free diagnostic."""
    try:
        path=Path(os.environ.get("TRADING_SIM_PUBLISH_STATUS_PATH") or STATUS_FILE)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(message+"\n",encoding="utf-8")
    except OSError:
        # Status recording must never expose confidential paths or credentials.
        pass

def main(argv=None)->int:
    args=list(sys.argv[1:] if argv is None else argv)
    if len(args)!=1:
        status="Expected one Cloudflare tunnel URL. Run start-private-bridge.ps1 instead."
        _save_status(status)
        print("[publisher] "+status,file=sys.stderr)
        return 2
    try:
        publish(args[0])
    except (RuntimeError,ValueError) as exc:
        # The known exceptions have static descriptions, not raw API bodies.
        status=str(exc)
        _save_status(status)
        print("[publisher] "+status,file=sys.stderr)
        return 1
    except Exception as exc:
        # Unexpected failures can contain sensitive URL or token details.
        status="Unexpected Python publisher error: "+type(exc).__name__+". Check local environment."
        _save_status(status)
        print("[publisher] "+status,file=sys.stderr)
        return 1
    _save_status("OK")
    return 0

if __name__=="__main__":
    sys.exit(main())
