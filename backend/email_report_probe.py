"""Manually approved email report diagnostic.

Never print private trading information, recipients, SMTP secrets or SMTP errors.
"""
import sys
from . import live_email_digest


def main():
    try:
        live_email_digest.send_now()
    except Exception as exc:
        print("[email] Report not sent; check local SMTP settings and connectivity. Error class: "
              +type(exc).__name__, file=sys.stderr)
        return 1
    print("[email] Report accepted by your configured SMTP server for delivery.")
    return 0


if __name__=="__main__":
    sys.exit(main())
