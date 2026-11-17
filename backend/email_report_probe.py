"""Safe interactive SMTP diagnostics and manually approved email report.

Tests authentication without sending when --diagnose is used. Never print
SMTP server responses, account addresses, app passwords, report bodies or URLs.
"""
from __future__ import annotations

import os
import sys

from . import live_email_digest, live_notifications


def diagnose():
    host = os.environ.get("TRADING_SIM_SMTP_HOST", "").strip()
    user = os.environ.get("TRADING_SIM_SMTP_USER", "").strip()
    password = os.environ.get("TRADING_SIM_SMTP_PASSWORD", "")
    if not host or not user or not password:
        print("[email] SMTP server, username or password is missing from your private .env.", file=sys.stderr)
        return 2
    if host.lower() == "smtp.gmail.com":
        compact = "".join(password.split())
        if len(compact) != 16:
            print("[email] Gmail credential format INVALID: expected a 16-character Google app password.", file=sys.stderr)
            print("[email] No login was attempted. Generate an app password at https://myaccount.google.com/apppasswords", file=sys.stderr)
            return 2
        password = compact
        print("[email] Gmail app password length is valid (this does not confirm the password itself).")
        if user.lower().endswith("@gmail.com"):
            print("[email] SMTP username format: consumer Gmail account.")
        else:
            print("[email] SMTP username format: non-Gmail address. Confirm the account owns the SMTP credential.")
    requested = int(os.environ.get("TRADING_SIM_SMTP_PORT", "465"))
    if requested not in (465, 587):
        print("[email] SMTP port must be 465 (SSL) or 587 (STARTTLS).", file=sys.stderr)
        return 2
    ports = [requested]
    if host.lower() == "smtp.gmail.com":
        ports.append(587 if requested == 465 else 465)
    success = False
    print("[email] Checking encrypted SMTP connection and login. No message will be sent.")
    for port in ports:
        label = "SSL" if port == 465 else "STARTTLS"
        try:
            smtp = live_notifications._smtp_connect_and_auth(host, port, user, password)
            try:
                success = True
                print(f"[email] {port} {label}: connection, TLS and authentication OK.")
            finally:
                try:
                    smtp.close()
                except Exception:
                    pass
        except live_notifications.SMTPDeliveryFailure as exc:
            print(f"[email] {port} {label}: {exc.stage} FAILED ({exc.cause}).")
        except Exception as exc:
            print(f"[email] {port} {label}: validation failed ({type(exc).__name__}).")
    if success:
        print("[email] Secure SMTP access is working. You can retry -SendEmailReport.")
        return 0
    print("[email] Neither tested connection authenticated. Check Gmail app password and network access.")
    return 1


def main():
    if "--diagnose" in sys.argv[1:]:
        return diagnose()
    try:
        live_email_digest.send_now()
    except live_notifications.SMTPDeliveryFailure as exc:
        if exc.stage == "deliver":
            print("[email] Message delivery was NOT CONFIRMED. Check recipients before retrying. "
                  f"SMTP stage: {exc.stage}, port: {exc.port}, error: {exc.cause}.",file=sys.stderr)
        else:
            print("[email] Report not sent. "
                  f"SMTP stage: {exc.stage}, port: {exc.port}, error: {exc.cause}. "
                  "Run -DiagnoseEmail for connection tests.",file=sys.stderr)
        return 1
    except Exception as exc:
        print("[email] Report not sent; check local SMTP settings and connectivity. Error class: "
              +type(exc).__name__,file=sys.stderr)
        return 1
    print("[email] Report accepted by your configured SMTP server for delivery.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
