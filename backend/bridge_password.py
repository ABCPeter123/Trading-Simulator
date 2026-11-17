"""Owner-hosted password authentication for private browser sessions.

The website never stores a password or an API token. Password verifiers are
generated and stored ONLY on the owner's computer. Session tokens live only
in backend RAM and browser tab memory, expire automatically and are revocable.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict

HASH_ITERATIONS=310_000
SESSION_SECONDS=8*3600
WINDOW_SECONDS=600
_LOCK=threading.RLock()
_SESSIONS:dict[str,float]={}
_FAILS:dict[str,list[float]]=defaultdict(list)
_GLOBAL_FAILS:list[float]=[]

def hash_password(password:str)->str:
    if len(password)<12 or len(password)>128:
        raise ValueError("Choose a password between 12 and 128 characters.")
    salt=os.urandom(24)
    digest=hashlib.pbkdf2_hmac("sha256",password.encode("utf-8"),salt,HASH_ITERATIONS)
    return "pbkdf2-sha256$"+str(HASH_ITERATIONS)+"$"+base64.b64encode(salt).decode()+"$"+base64.b64encode(digest).decode()

def verify(password:str,encoded:str)->bool:
    try:
        scheme,iterations,salt,digest=encoded.split("$")
        if scheme!="pbkdf2-sha256" or int(iterations)<250_000 or int(iterations)>1_000_000:
            return False
        if not isinstance(password,str) or len(password)>128 or len(password)<1:return False
        calculated=hashlib.pbkdf2_hmac("sha256",password.encode("utf-8"),
            base64.b64decode(salt,validate=True),int(iterations))
        return hmac.compare_digest(calculated,base64.b64decode(digest,validate=True))
    except (ValueError,TypeError,OverflowError):
        return False

def new_session(password:str,encoded:str,ip:str)->str|None:
    now=time.monotonic()
    identity=ip[:96] if ip else "unknown"
    with _LOCK:
        _FAILS[identity]=[x for x in _FAILS[identity] if now-x<WINDOW_SECONDS]
        _GLOBAL_FAILS[:]=[x for x in _GLOBAL_FAILS if now-x<WINDOW_SECONDS]
        if len(_FAILS[identity])>=5 or len(_GLOBAL_FAILS)>=120:
            return None
    good=verify(password,encoded)
    with _LOCK:
        if not good:
            _FAILS[identity].append(now)
            _GLOBAL_FAILS.append(now)
            return None
        _FAILS.pop(identity,None)
        for key,expiry in list(_SESSIONS.items()):
            if expiry<=now: _SESSIONS.pop(key,None)
        if len(_SESSIONS)>=128:return None
        token=secrets.token_urlsafe(48)
        _SESSIONS[hashlib.sha256(token.encode()).hexdigest()]=now+SESSION_SECONDS
        return token

def authenticated(authorization:str)->bool:
    if not authorization.startswith("Bearer "):return False
    token=authorization[7:]
    if len(token)>200 or not token:return False
    fingerprint=hashlib.sha256(token.encode()).hexdigest()
    with _LOCK:
        expiry=_SESSIONS.get(fingerprint,0)
        if expiry<=time.monotonic():
            _SESSIONS.pop(fingerprint,None)
            return False
    return True

def revoke(authorization:str):
    if authorization.startswith("Bearer "):
        with _LOCK:
            _SESSIONS.pop(hashlib.sha256(authorization[7:].encode()).hexdigest(),None)
