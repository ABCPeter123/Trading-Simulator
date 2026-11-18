"""Bounded local market ingestion worker; no cloud/paid services required."""
from __future__ import annotations
import argparse
import logging
import signal
import time
from . import market_ingestion

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--interval",type=int,default=30)
    args=parser.parse_args()
    if not 10<=args.interval<=600:parser.error("Interval must be 10-600 seconds.")
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGINT,stop)
    if hasattr(signal,"SIGTERM"):signal.signal(signal.SIGTERM,stop)
    while not stopping:
        try:
            market_ingestion.record_heartbeat("polling")
            updates = market_ingestion.run_due()
            for item in updates:
                # No prices, credentials, or owner strategy data are logged.
                if "error" in item:
                    logging.warning("Market sync unavailable: %s",item["error"])
            # Run one durable history/reconciliation job at most per cycle.
            # Every active feed gets a chance to poll fresh bars before the
            # slower verification or repair job begins.
            repairs = market_ingestion.run_reconciliation_due()
            for job in repairs:
                if job.get("error"):
                    logging.warning("Historical verification pending retry: %s", job["error"])
            market_ingestion.record_heartbeat("idle", len(updates)+len(repairs))
        except Exception as exc:
            logging.error("Market ingestion worker failed: %s",type(exc).__name__)
        if args.once:break
        for _ in range(args.interval):
            if stopping:break
            time.sleep(1)
    return 0
if __name__=="__main__":
    raise SystemExit(main())
