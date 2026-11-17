"""One-off owner-confirmed iMessage transport check, invoked by the Windows launcher.

This is an outbound test only and never reads strategies or a trading database.
Credentials are loaded by start-live-machine.ps1 into process memory.
"""
from __future__ import annotations

import sys
from . import live_notifications as notifications


def main() -> int:
    if "imessage" not in notifications._channels():
        print("[iMessage] Configure the Mac server URL, password and iMessage chat GUID in your private .env.", file=sys.stderr)
        return 2
    try:
        notifications._send_imessage(
            "TEST",
            "Connection test from Trading Simulator. No strategy or trading data is included.",
        )
    except Exception as exc:
        # Provider exceptions may include the relay password or recipient.
        # Never print exception values, HTTP request URLs, or response bodies.
        print("[iMessage] Test failed. Check Mac relay connectivity and settings (error type: "+type(exc).__name__+").",file=sys.stderr)
        return 1
    print("[iMessage] Relay accepted the test message. Verify receipt on your Apple device.")
    return 0


if __name__=="__main__":
    sys.exit(main())
