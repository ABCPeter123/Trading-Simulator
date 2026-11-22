"""Keyless GDELT headline ingestion with local timestamp-safe sentiment archive.

News available to a strategy is determined by when THIS MACHINE observed it,
never a retroactively downloaded article's publication timestamp. Headlines
are not allowed to rewrite yesterday's portfolio decisions.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from threading import RLock
from contextlib import closing
from urllib.parse import urlparse
import math
import os
import re
import sqlite3
import time
import httpx

from fastapi import HTTPException
from .assets import get_instrument

DB_PATH=Path(os.environ.get("TRADING_SIM_PRIVATE_NEWS_DB",
    Path(__file__).resolve().parents[1]/"data/news_sentiment.sqlite3"))
LOCK=RLock()
BASE_URL="https://api.gdeltproject.org/api/v2/doc/doc"
MAX_SYMBOLS=5
MAX_ARTICLES=150
MIN_REFRESH_SECONDS=900
POSITIVE=(
    "beats estimates","beats expectations","raises guidance","raises forecast",
    "strong demand","new contract","wins contract","contract awarded",
    "record revenue","record profit","profit jumps","revenue surges",
    "earnings beat","sales beat","upgrade","upgraded","approval granted",
    "regulatory approval","orders surge","revenue growth","profit rises",
)
NEGATIVE=(
    "misses estimates","misses expectations","cuts guidance","cuts forecast",
    "weak demand","contract cancelled","contract canceled","profit warning",
    "downgrade","downgraded","lawsuit","investigation","under investigation",
    "recall","fraud","bankruptcy","earnings miss","loss widens",
    "revenue falls","supply shortage","regulatory ban","fine imposed",
)
MARKET_TERMS={
    "spy":'("S&P 500" OR "US stock market")',
    "qqq":'("Nasdaq 100" OR "technology stocks")',
    "vti":'("US stock market" OR "S&P 500")',
    "ief":'("US Treasury yields" OR "Treasury bonds")',
    "tlt":'("long-term Treasury" OR "Treasury yields")',
    "gld":'("gold prices" OR "gold bullion")',
}
_client=httpx.Client(timeout=18,headers={"User-Agent":"TradingSimLocalResearch/1.0"})


def _db():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DB_PATH,timeout=10)
    conn.row_factory=sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS articles(
        symbol TEXT NOT NULL,url TEXT NOT NULL,title TEXT NOT NULL,
        domain TEXT NOT NULL,published_utc INTEGER NOT NULL,
        first_observed_utc INTEGER NOT NULL,source TEXT NOT NULL,
        PRIMARY KEY(symbol,url))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS feed_checks(
        symbol TEXT PRIMARY KEY,checked_utc INTEGER NOT NULL,
        provider TEXT NOT NULL,provider_count INTEGER NOT NULL)""")
    conn.commit()
    return conn


def _symbols(symbols):
    if (not isinstance(symbols,list) or not 1<=len(symbols)<=MAX_SYMBOLS
            or any(not isinstance(s,str) or len(s)>16 for s in symbols)):
        raise HTTPException(422,"Choose one to five catalog symbols.")
    ids=[s.strip().lower() for s in symbols]
    if len(set(ids))!=len(ids):
        raise HTTPException(422,"Duplicate news symbols.")
    for symbol in ids:
        try: instrument=get_instrument(symbol)
        except (ValueError,KeyError,HTTPException):
            raise HTTPException(422,"Unknown catalog instrument.") from None
        if instrument.kind not in ("Stocks","ETFs"):
            raise HTTPException(422,"News sentiment supports listed stocks and ETFs.")
    return ids


def _query(symbol):
    if symbol in MARKET_TERMS:return MARKET_TERMS[symbol]
    instrument=get_instrument(symbol)
    label=instrument.name or instrument.ticker
    label=re.sub(r'[^a-zA-Z0-9 &.\-]',' ',label).strip()
    if len(label)<3:raise ValueError("Ambiguous instrument name.")
    return '"'+label+'"'


def _timestamp(value):
    if type(value) in (int,float):
        return int(value)
    if not isinstance(value,str):raise ValueError("Unparseable headline timestamp.")
    raw=value.strip()
    for pattern in ("%Y%m%dT%H%M%SZ","%Y%m%d%H%M%S"):
        try:return int(datetime.strptime(raw,pattern).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:pass
    try:return int(datetime.fromisoformat(raw.replace("Z","+00:00")).timestamp())
    except ValueError as exc:raise ValueError("Unparseable headline timestamp.") from exc


def sentiment(title):
    """Transparent event-aware English headline heuristic, not learned alpha."""
    if not isinstance(title,str):return 0.
    lowered=" "+re.sub(r'[^a-z0-9%$ .]',' ',title.lower())+" "
    positive=sum(term in lowered for term in POSITIVE)
    negative=sum(term in lowered for term in NEGATIVE)
    if positive==negative:return 0.
    direction=1 if positive>negative else -1
    strength=min(1.,.55+.17*abs(positive-negative))
    if any(term in lowered for term in ("earnings","guidance","contract","revenue","profit")):
        strength=min(1.,strength*1.13)
    return round(direction*strength,4)


def _fetch(symbol, client):
    response=client.get(BASE_URL,params={
        "query":_query(symbol)+" sourcelang:english",
        "mode":"artlist","format":"json","timespan":"3d",
        "maxrecords":MAX_ARTICLES,"sort":"datedesc"})
    response.raise_for_status()
    data=response.json()
    if not isinstance(data,dict) or not isinstance(data.get("articles"),list):
        raise ValueError("GDELT returned an invalid or empty article payload.")
    return data["articles"]


def refresh(symbols,*,client=None,now=None,pause=time.sleep):
    """Explicit bounded fetch; no API key or automatic paid endpoint."""
    ids=_symbols(symbols)
    observed=int((now or datetime.now(timezone.utc)).timestamp())
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise HTTPException(403,"Private news archiving unavailable in public demo.")
    output=[]
    for i,symbol in enumerate(ids):
        with LOCK,closing(_db()) as conn:
            recent=conn.execute("SELECT checked_utc FROM feed_checks WHERE symbol=?",
                                (symbol,)).fetchone()
        if recent is not None and observed-recent["checked_utc"]<MIN_REFRESH_SECONDS:
            output.append({"symbol":symbol,"status":"cached","new_articles":0})
            continue
        if i:
            # GDELT asks clients to issue low-frequency search requests.
            pause(5.)
        try:
            incoming=_fetch(symbol,client or _client)
            new=0
            with LOCK,closing(_db()) as conn,conn:
                for item in incoming:
                    if not isinstance(item,dict):continue
                    title=str(item.get("title") or "").strip()[:450]
                    url=str(item.get("url") or "").strip()[:1600]
                    parsed=urlparse(url)
                    if (not title or parsed.scheme not in ("http","https")
                        or not parsed.hostname or len(title)<10):continue
                    try:published=_timestamp(item.get("seendate"))
                    except (ValueError,TypeError):continue
                    if published>observed+300 or observed-published>100*86400:
                        continue
                    # This is the earliest usable time, even for older articles.
                    count=conn.execute("""INSERT OR IGNORE INTO articles
                        (symbol,url,title,domain,published_utc,first_observed_utc,source)
                        VALUES(?,?,?,?,?,?,?)""",
                        (symbol,url,title,parsed.hostname.lower(),published,observed,"GDELT DOC 2.0"))
                    new+=max(0,count.rowcount)
                conn.execute("""INSERT INTO feed_checks(symbol,checked_utc,provider,provider_count)
                    VALUES(?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET
                    checked_utc=excluded.checked_utc,provider_count=excluded.provider_count""",
                    (symbol,observed,"GDELT DOC 2.0",len(incoming)))
            output.append({"symbol":symbol,"status":"updated","new_articles":new,
                           "provider_records":len(incoming),
                           "result_truncated":len(incoming)>=MAX_ARTICLES})
        except (httpx.HTTPError,ValueError,sqlite3.Error):
            output.append({"symbol":symbol,"status":"provider_unavailable",
                           "new_articles":0})
    return {"source":"GDELT DOC 2.0","key_required":False,
            "archival_rule":"Only observed-at timestamps may be used by later signals",
            "results":output}


def scores_at(symbols,at,*,hours=72):
    """Only rows that had ALREADY ARRIVED at the requested decision instant."""
    stamp=_timestamp(at)
    results={}
    with LOCK,closing(_db()) as conn:
        for symbol in symbols:
            rows=conn.execute("""SELECT title,first_observed_utc,published_utc
                 FROM articles WHERE symbol=? AND first_observed_utc<=?
                 AND published_utc<=? AND first_observed_utc>=?
                 ORDER BY first_observed_utc DESC LIMIT 100""",
                 (symbol,stamp,stamp,stamp-int(hours*3600))).fetchall()
            scored=[]; seen=set()
            for article in rows:
                title=str(article["title"])
                canon=re.sub(r'[^a-z0-9]','',title.lower())
                if canon in seen:continue
                seen.add(canon)
                raw=sentiment(title)
                age=max(0,stamp-max(article["first_observed_utc"],article["published_utc"]))
                weight=2**(-age/(18*3600.))
                if raw:scored.append((raw,weight))
            if scored:
                score=sum(x*w for x,w in scored)/sum(w for _,w in scored)
                results[symbol]={"score":round(score,4),"direction":(
                    "positive" if score>.2 else "negative" if score<-.2 else "mixed"),
                    "scored_headlines":len(scored)}
            else:
                results[symbol]={"score":None,"direction":"insufficient_news",
                                 "scored_headlines":0}
    return results


def snapshot(symbols,*,now=None):
    ids=_symbols(symbols)
    stamp=int((now or datetime.now(timezone.utc)).timestamp())
    with LOCK,closing(_db()) as conn:
        data={}
        for symbol in ids:
            check=conn.execute("SELECT checked_utc,provider_count FROM feed_checks WHERE symbol=?",(symbol,)).fetchone()
            articles=conn.execute("""SELECT title,url,domain,published_utc,first_observed_utc
                FROM articles WHERE symbol=? AND first_observed_utc<=?
                ORDER BY first_observed_utc DESC LIMIT 10""",(symbol,stamp)).fetchall()
            data[symbol]={"latest_refresh":check["checked_utc"] if check else None,
                          "provider_result_count":check["provider_count"] if check else 0,
                          "headlines":[dict(a) for a in articles]}
    return {"provider":"GDELT DOC 2.0","free":True,
            "scores":scores_at(ids,stamp),"instruments":data,
            "prediction_status":"unvalidated forward-looking headline heuristic",
            "history_warning":"Backtest cannot use articles published before they were actually archived by this machine."}


def risk_tilt(weights,scores):
    """Reduce, never raise, exposure on negative observed news.

    A conservative shadow-paper experiment: no net short, invented hedges or
    extra gross investment. No headlines means original frozen allocation.
    """
    adjusted={}
    for symbol,weight in weights.items():
        signal=scores.get(symbol,{})
        score=signal.get("score") if isinstance(signal,dict) else None
        adjusted[symbol]=float(weight)*(1-.35*min(1.,max(0.,-score))) if score is not None else float(weight)
    return adjusted
