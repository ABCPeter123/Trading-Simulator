"""Dedicated private laptop research worker.

The browser and Vercel only enqueue and read job records. This independent
process executes bounded fixed research operations using local SQLite and
market feeds. Worker stdout never includes strategy data or full exceptions.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time

from . import research_queue, universe_research, strategy_period_queue


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--interval",type=int,default=3)
    opts=parser.parse_args(argv)
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise RuntimeError("Private research worker cannot run in demo mode.")
    if not 1<=opts.interval<=60:
        parser.error("Research poll interval must be 1-60 seconds.")
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    stop=False
    def shutdown(_signal,_frame):
        nonlocal stop
        stop=True
    signal.signal(signal.SIGINT,shutdown)
    if hasattr(signal,"SIGTERM"):signal.signal(signal.SIGTERM,shutdown)
    while not stop:
        try:
            job=strategy_period_queue.process_one()
            if job is None:
                job=universe_research.process_one()
            if job is None:
                job=research_queue.process_one()
            if job is not None:
                # No symbols, parameters or results in public/local logs.
                logging.info("Research job finished with status %s",job["status"])
        except Exception as exc:
            logging.error("Research worker cycle error: %s",type(exc).__name__)
        if opts.once:break
        for _ in range(opts.interval):
            if stop:break
            time.sleep(1)
    return 0


if __name__=="__main__":
    sys.exit(main())
