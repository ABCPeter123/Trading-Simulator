"""Install the fail-closed staged-file privacy gate in this Git checkout.

Does not overwrite or disable another pre-commit hook. Run once per clone;
start-local.ps1 installs it automatically during normal setup.
"""
from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path

MARKER = "trading-simulator-privacy-hook"
HOOK = """#!/bin/sh
# trading-simulator-privacy-hook: checked Git index is the source of truth.
set -eu
cd "$(git rev-parse --show-toplevel)" || exit 1
if [ -f .venv/Scripts/python.exe ]; then
    exec .venv/Scripts/python.exe scripts/check_private_artifacts.py --staged
elif [ -f .venv/bin/python ]; then
    exec .venv/bin/python scripts/check_private_artifacts.py --staged
elif command -v python3 >/dev/null 2>&1; then
    exec python3 scripts/check_private_artifacts.py --staged
elif command -v python >/dev/null 2>&1; then
    exec python scripts/check_private_artifacts.py --staged
elif command -v py >/dev/null 2>&1; then
    exec py -3 scripts/check_private_artifacts.py --staged
else
    echo "Privacy check blocked commit: Python is not available." >&2
    exit 1
fi
"""

def install() -> int:
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks"],
        cwd=root, capture_output=True, text=True,
    )
    if result.returncode:
        print("[privacy] Not a Git checkout; skipping local hook (CI still scans Git).")
        return 0
    hooks = Path(result.stdout.strip())
    if not hooks.is_absolute():
        hooks = root / hooks
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-commit"
    if hook.exists():
        if MARKER in hook.read_text(encoding="utf-8", errors="replace"):
            print("[privacy] Local pre-commit privacy check already installed.")
            return 0
        print(
            "[privacy] Existing pre-commit hook was NOT changed. Add "
            "'python scripts/check_private_artifacts.py --staged' to your hook "
            "to enforce privacy locally. GitHub CI still blocks detected leaks.",
            file=sys.stderr,
        )
        return 0
    hook.write_text(HOOK, encoding="utf-8", newline="\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print("[privacy] Installed local Git pre-commit guard for private strategy data.")
    return 0

if __name__ == "__main__":
    sys.exit(install())
