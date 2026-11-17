"""One-shot private cross-asset model research.

Run via start-live-machine.ps1 -ComparePortfolio [-PortfolioAssets "spy,ief,gld,..."].
Private results remain in data/portfolio_research.sqlite3.
"""
from __future__ import annotations
import argparse
import os
import sys
from . import portfolio_research as research
from . import live_email_digest, live_notifications


def main(argv=None):
    parser=argparse.ArgumentParser(description="Private multi-asset portfolio model comparison")
    parser.add_argument("--symbols",default="spy,qqq,ief,gld,eem,vnq")
    parser.add_argument("--max-drawdown",type=float,default=25.)
    parser.add_argument("--max-weight",type=float,default=35.)
    parser.add_argument("--email",action="store_true",help="send complete private briefing after research")
    args=parser.parse_args(argv)
    symbols=[x.strip().lower() for x in args.symbols.split(",") if x.strip()]
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        print("[research] Portfolio research is unavailable in public demo.")
        return 2
    try:
        result=research.compare(symbols,max_drawdown_pct=args.max_drawdown,
                                max_position_pct=args.max_weight)
    except Exception as exc:
        # Provider HTTP failures and local disk exceptions may contain
        # confidential account data; print only the exception class.
        print("[research] Historical portfolio analysis failed ("+type(exc).__name__+
              "). Check local provider availability, symbols and 5-year coverage.",file=sys.stderr)
        return 1
    print("[research] Multi-asset portfolio research saved locally.")
    print("[research] Assets: "+", ".join(x.upper() for x in result["basket"]))
    print("[research] Models: "+str(result["candidate_count"])+
          "; qualified under validation risk limits: "+str(result["eligible_count"]))
    for candidate in result["candidates"]:
        valid=candidate["validation"]
        print("[research] "+candidate["model"]+
              " | validation net return "+format(valid["return_pct"],".2f")+"%"+
              " | max drawdown "+format(valid["max_drawdown_pct"],".2f")+"%"+
              " | Sharpe "+(format(valid["sharpe"],".2f") if valid["sharpe"] is not None else "N/A")+
              " | turnover "+format(valid["turnover_pct"],".2f")+"%"+
              " | qualified "+("yes" if candidate["qualified"] else "no"))
    winner=result["selected"]
    if winner:
        test=winner["held_out_test"]
        benchmark=winner["held_out_equal_weight_benchmark"]
        print("[research] Validation-selected model: "+winner["model"])
        print("[research] HELD-OUT historical return: "+format(test["return_pct"],".2f")+
              "% vs equal-weight "+format(benchmark["return_pct"],".2f")+"%")
        print("[research] HELD-OUT drawdown: "+format(test["max_drawdown_pct"],".2f")+
              "%; fees (USD): "+format(test["fees"],".2f"))
    else:
        print("[research] No candidate passed validation. No model selected or deployed.")
    if args.email:
        try:
            if "email" not in live_notifications._channels():
                raise ValueError("SMTP not configured")
            subject,body,html=live_email_digest.build_report()
            live_notifications._send_email(subject,body,html)
            print("[research] Private portfolio results included in email briefing accepted by SMTP.")
        except Exception as exc:
            print("[research] Portfolio study was saved, but the email failed ("+type(exc).__name__+").",
                  file=sys.stderr)
            return 1
    print("[research] Models are hypothetical only. No broker orders or live deployments occurred.")
    return 0


if __name__=="__main__":
    sys.exit(main())
