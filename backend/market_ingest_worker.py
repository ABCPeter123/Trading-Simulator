"""Bounded local market ingestion worker; no cloud/paid services required."""
from __future__ import annotations
import argparse
import logging
import signal
import time
from threading import Event, Thread
from . import market_ingestion

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--interval",type=int,default=30)
    args=parser.parse_args()
    if not 10<=args.interval<=600:parser.error("Interval must be 10-600 seconds.")
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    stop_event = Event()
    def stop(*_):
        stop_event.set()
    signal.signal(signal.SIGINT, stop)
    if hasattr(signal,"SIGTERM"):
        signal.signal(signal.SIGTERM, stop)

    def reconcile_loop():
        # Separate I/O thread: slow MAX downloads must not stall the feed
        # poller. At most one history request is in flight per local worker.
        while not stop_event.is_set():
            try:
                for job in market_ingestion.run_reconciliation_due():
                    if job.get("error"):
                        logging.warning("Historical verification pending retry: %s",
                                        job["error"])
            except Exception as exc:
                logging.error("Reconciliation worker failed: %s",type(exc).__name__)
            stop_event.wait(args.interval)

    repair_thread = None
    if not args.once:
        repair_thread = Thread(target=reconcile_loop, name="market-reconcile",
                               daemon=True)
        repair_thread.start()
    while not stop_event.is_set():
        try:
            market_ingestion.record_heartbeat("polling")
            updates = market_ingestion.run_due()
            for item in updates:
                # No prices, credentials, or owner strategy data are logged.
                if "error" in item:
                    logging.warning("Market sync unavailable: %s",item["error"])
            market_ingestion.record_heartbeat("idle", len(updates))
        except Exception as exc:
            logging.error("Market ingestion worker failed: %s",type(exc).__name__)
        if args.once:
            try:
                market_ingestion.run_reconciliation_due()
            except Exception as exc:
                logging.error("Reconciliation worker failed: %s",type(exc).__name__)
            break
        stop_event.wait(args.interval)
    stop_event.set()
    if repair_thread:
        repair_thread.join(timeout=2)
    return 0
if __name__=="__main__":
    raise SystemExit(main())
