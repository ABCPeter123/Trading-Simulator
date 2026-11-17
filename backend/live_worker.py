"""Independent local always-running daily signal/alert worker.

Run: python -m backend.live_worker
Optional: --once for safe one-cycle diagnostics.
Unlike a browser page, this stays alive until the operator stops the process.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time

from . import live_machine, live_notifications

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--interval",type=int,default=90)
    args=parser.parse_args()
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise RuntimeError("Live worker is disabled in public demo mode.")
    if args.interval<30 or args.interval>3600:
        parser.error("Worker interval must be 30-3600 seconds.")
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    should_stop=False
    def request_stop(signum, frame):
        nonlocal should_stop
        should_stop=True
    signal.signal(signal.SIGINT,request_stop)
    if hasattr(signal,"SIGTERM"):signal.signal(signal.SIGTERM,request_stop)
    while not should_stop:
        try:
            live_machine.run_once()
            live_notifications.deliver_pending()
        except Exception as exc:
            # Worker errors must not leak credentials or saved strategy programs.
            logging.error("Live machine cycle failed: %s",type(exc).__name__)
            try:
                live_machine.record_alert("worker:failure","critical",
                    "Strategy machine cycle failed",
                    "Check the local worker logs. Signals may be delayed until recovery.")
            except Exception:
                logging.error("Could not write local worker fault alert.")
        if args.once:break
        for _ in range(args.interval):
            if should_stop:break
            time.sleep(1)
    return 0

if __name__=="__main__":
    sys.exit(main())
