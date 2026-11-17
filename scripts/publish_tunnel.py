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
TUNNEL=re.compile(r"^https://[a-z0-9-]+\.trycloudflare\.com$")

def publish(url:str):
    if not TUNNEL.fullmatch(url):
        raise ValueError("Expected a Cloudflare Quick Tunnel HTTPS origin.")
    token=os.environ.get("TRADING_SIM_VERCEL_TOKEN","").strip()
    if not token and TOKEN_FILE.exists():
        token=TOKEN_FILE.read_text(encoding="utf-8").strip()
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

if __name__=="__main__":
    if len(sys.argv)!=2:
        raise SystemExit("Use: python scripts/publish_tunnel.py https://...trycloudflare.com")
    try:publish(sys.argv[1])
    except (ValueError,RuntimeError) as error:raise SystemExit(str(error))
