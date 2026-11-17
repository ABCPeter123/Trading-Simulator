"""Create local password hash without placing the password in Git or cloud.

No plaintext password, hash or user strategy should appear in stdout.
"""
from __future__ import annotations
import getpass
import os
from pathlib import Path
from backend.bridge_password import hash_password

def main():
    path=Path(__file__).resolve().parents[1]/".local-state/private-bridge/password-hash.txt"
    path.parent.mkdir(parents=True,exist_ok=True)
    a=getpass.getpass("Choose the shared web access password (12+ characters): ")
    b=getpass.getpass("Confirm the shared password: ")
    if a!=b:
        raise SystemExit("Passwords do not match. No change made.")
    try: value=hash_password(a)
    except ValueError as e:raise SystemExit(str(e))
    temp=path.with_suffix(".tmp")
    temp.write_text(value,encoding="ascii")
    os.replace(temp,path)
    print("Shared web password configured locally. Its plaintext is not saved.")
if __name__=="__main__":main()
