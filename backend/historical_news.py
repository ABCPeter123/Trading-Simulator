"""Free historical GDELT GKG 1.0 daily archive, April 2013 onwards.

Historical GKG contains aggregate nameset tone, not headline text. Downloads
are bounded, streamed, temporary and never committed to GitHub. Backfilled
values are only eligible for *retrospective* daily research after a conservative
next-day-archive lag; they must never feed the real-time first-observed news API.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, time as clock_time, timedelta, timezone
from io import TextIOWrapper
from pathlib import Path
from tempfile import SpooledTemporaryFile
from threading import RLock
from urllib.parse import urlparse
from uuid import uuid4
from zipfile import BadZipFile, ZipFile
import json
import math
import os
import re
import sqlite3
import time

import httpx
from fastapi import HTTPException

from .assets import get_instrument

BASE="https://data.gdeltproject.org/gkg"
FIRST_DATE=date(2013,4,1)
DB_PATH=Path(os.environ.get("TRADING_SIM_HISTORICAL_NEWS_DB",
    Path(__file__).resolve().parents[1]/"data/historical_news.sqlite3"))
LOCK=RLock()
MAX_DAYS_PER_JOB=31
MAX_SYMBOLS=5
MAX_COMPRESSED_BYTES=80*1024*1024
MAX_EXPANDED_BYTES=900*1024*1024
MAX_ROWS=1_200_000
SOURCE="GDELT GKG 1.0 daily"
# Only exact known organization names or reasonably unambiguous aliases.
# Do not match ticker acronyms inside unrelated organizations.
ALIASES={
    "nvda":("nvidia","nvidia corporation"),
    "aapl":("apple","apple inc","apple computer"),
    "msft":("microsoft","microsoft corporation"),
    "goog":("google","alphabet","alphabet inc"),
    "googl":("google","alphabet","alphabet inc"),
    "amzn":("amazon","amazon com","amazon.com"),
    "tsla":("tesla","tesla motors","tesla inc"),
    "meta":("meta platforms","facebook","facebook inc"),
    "amd":("advanced micro devices","amd"),
    "orcl":("oracle","oracle corporation"),
    "jpm":("jpmorgan chase","jpmorgan","jp morgan chase"),
    "pltr":("palantir","palantir technologies"),
    "nflx":("netflix","netflix inc"),
    "hood":("robinhood","robinhood markets"),
}


def _now():return datetime.now(timezone.utc)


def _db():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(DB_PATH,timeout=15)
    c.row_factory=sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS historic_news_jobs(
        id TEXT PRIMARY KEY,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
        params TEXT NOT NULL,status TEXT NOT NULL,processed_days INTEGER NOT NULL,
        total_days INTEGER NOT NULL,stage TEXT NOT NULL,error_code TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS historic_news_coverage(
        symbol TEXT NOT NULL,news_day TEXT NOT NULL,
        source TEXT NOT NULL,archive_url TEXT NOT NULL,
        archive_research_available_utc INTEGER NOT NULL,
        checked_utc INTEGER NOT NULL,rows_scanned INTEGER NOT NULL,
        namesets INTEGER NOT NULL,mentions INTEGER NOT NULL,
        PRIMARY KEY(symbol,news_day))""")
    c.execute("""CREATE TABLE IF NOT EXISTS historic_news_tone(
        symbol TEXT NOT NULL,news_day TEXT NOT NULL,
        raw_tone REAL NOT NULL,score REAL NOT NULL,
        namesets INTEGER NOT NULL,mentions INTEGER NOT NULL,
        PRIMARY KEY(symbol,news_day))""")
    c.commit()
    return c


def _canonical(value):
    return " ".join(re.findall(r"[a-z0-9]+",str(value).lower()))


def _aliases(symbol):
    instrument=get_instrument(symbol)
    name=_canonical(instrument.name)
    stripped=re.sub(r"\b(incorporated|inc|corporation|corp|limited|ltd|holdings|company|co|class [a-z])\b","",name)
    values=set(ALIASES.get(symbol,()))
    values.update((name," ".join(stripped.split())))
    return {v for v in (_canonical(x) for x in values) if len(v)>=4}


def _symbols(symbols):
    if (type(symbols) is not list or not 1<=len(symbols)<=MAX_SYMBOLS
        or any(not isinstance(s,str) or not 1<=len(s)<=16 for s in symbols)):
        raise HTTPException(422,"Choose one to five stock symbols.")
    result=[s.strip().lower() for s in symbols]
    if len(set(result))!=len(result):
        raise HTTPException(422,"Duplicate historical news symbols.")
    for sym in result:
        try:instrument=get_instrument(sym)
        except (HTTPException,KeyError,ValueError):
            raise HTTPException(422,"Unknown stock symbol.") from None
        if instrument.kind!="Stocks":
            raise HTTPException(422,"Historical GKG organization tone currently supports stocks, not ETF proxies.")
        if not _aliases(sym):
            raise HTTPException(422,"No unambiguous historical organization name.")
    return result


def _period(start_date,end_date,now=None):
    try:
        a=date.fromisoformat(start_date)
        b=date.fromisoformat(end_date)
    except (TypeError,ValueError):
        raise HTTPException(422,"Use ISO dates YYYY-MM-DD.") from None
    latest=(now or _now()).date()-timedelta(days=2)
    span=(b-a).days+1
    if a<FIRST_DATE or a>b or b>latest or not 1<=span<=MAX_DAYS_PER_JOB:
        raise HTTPException(422,"Select 1 to 31 complete daily GKG archive dates from 2013-04-01 through two days ago.")
    return a,b,span


def _archive_ready(day):
    """GKG 1.0 day D exports on D+1; conservatively allow from D+2 at NY open."""
    from zoneinfo import ZoneInfo
    et=ZoneInfo("America/New_York")
    available=datetime.combine(day+timedelta(days=2),clock_time(9,30),et)
    return int(available.timestamp())


def _parse_line(line,day,symbol_aliases):
    """GKG1 nameset columns: DATE, NUMARTS, COUNTS, THEMES,
    LOCATIONS, PERSONS, ORGANIZATIONS, TONE, CAMEOEVENTIDS, SOURCES, SOURCEURLS.
    Unlike GKG2.1 these rows are aggregated namesets, not individual news items.
    """
    fields=line.rstrip("\r\n").split("\t")
    if len(fields)<11 or fields[0]!=day.strftime("%Y%m%d"):
        return {}
    try:
        count=int(fields[1])
        tone=float(fields[7].split(",",1)[0])
    except (ValueError,IndexError):
        return {}
    if not (0<count<=1_000_000 and math.isfinite(tone) and -100<=tone<=100):
        return {}
    organizations={_canonical(x) for x in fields[6].split(";") if x.strip()}
    return {sym:(count,tone) for sym,aliases in symbol_aliases.items()
            if organizations.intersection(aliases)}


def parse_daily_zip(blob,day,symbols):
    """Stream one trusted-source archive directly from a capped ZIP.

    No full decompressed news dataset is copied to disk or memory.
    """
    aggregates={s:{"weighted":0.,"mentions":0,"namesets":0} for s in symbols}
    aliases={s:_aliases(s) for s in symbols}
    with ZipFile(blob) as z:
        members=[info for info in z.infolist()
                 if info.filename.lower().endswith(".gkg.csv")]
        if len(members)!=1:
            raise ValueError("Expected one GKG graph CSV entry, not a counts-only archive.")
        info=members[0]
        if not 0<info.file_size<=MAX_EXPANDED_BYTES:
            raise ValueError("Historical GKG archive exceeds decompression limit.")
        count=0
        with z.open(info) as member,TextIOWrapper(
                member,encoding="utf-8",errors="replace",newline="") as stream:
            for line in stream:
                count+=1
                if count>MAX_ROWS:
                    raise ValueError("Historical GKG archive exceeds row limit.")
                if len(line)>2_000_000:
                    raise ValueError("Oversized historical GKG row.")
                for sym,(mentions,tone) in _parse_line(line,day,aliases).items():
                    agg=aggregates[sym]
                    agg["weighted"]+=mentions*tone
                    agg["mentions"]+=mentions
                    agg["namesets"]+=1
        if count==0:
            raise ValueError("Historical archive contained no records.")
    result={}
    for sym,metric in aggregates.items():
        mentions=metric["mentions"]
        tone=metric["weighted"]/mentions if mentions else None
        result[sym]={"raw_tone":round(tone,6) if tone is not None else None,
                     "score":round(max(-1.,min(1.,tone/10)),6) if tone is not None else None,
                     "namesets":metric["namesets"],"mentions":mentions}
    return count,result


def fetch_daily(day,symbols,*,client=None):
    """One bounded HTTPS download. ZIP bytes are discarded after parsing."""
    url=BASE+"/"+day.strftime("%Y%m%d")+".gkg.csv.zip"
    getter=client or httpx.Client(timeout=httpx.Timeout(60,connect=12),
                                  follow_redirects=False)
    owned=client is None
    try:
        with SpooledTemporaryFile(max_size=8*1024*1024) as temporary:
            with getter.stream("GET",url) as response:
                response.raise_for_status()
                length=response.headers.get("content-length")
                if length and int(length)>MAX_COMPRESSED_BYTES:
                    raise ValueError("Historical news download exceeds per-day bandwidth limit.")
                total=0
                for chunk in response.iter_bytes(512*1024):
                    total+=len(chunk)
                    if total>MAX_COMPRESSED_BYTES:
                        raise ValueError("Historical news download exceeds per-day bandwidth limit.")
                    temporary.write(chunk)
            if total<30:
                raise ValueError("Historical news archive download is empty.")
            temporary.seek(0)
            rows,metrics=parse_daily_zip(temporary,day,symbols)
        return url,rows,metrics
    finally:
        if owned:getter.close()


def _public(row):
    x=dict(row)
    p=json.loads(x["params"])
    return {"id":x["id"],"created_at":x["created_at"],
            "updated_at":x["updated_at"],"status":x["status"],
            "params":p,"stage":x["stage"],"error_code":x["error_code"],
            "processed_days":x["processed_days"],"total_days":x["total_days"],
            "progress":round(100*x["processed_days"]/max(1,x["total_days"]),1)}


def enqueue(symbols,start_date,end_date,*,now=None):
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise HTTPException(403,"Historical private news backfill unavailable in demo mode.")
    ids=_symbols(symbols)
    _,_,days=_period(start_date,end_date,now)
    params={"symbols":ids,"start_date":start_date,"end_date":end_date,
            "source":SOURCE,"resolution":"daily",
            "estimated_download":"GKG full daily ZIP often 15-40MB per day; ZIP discarded after extraction."}
    label=json.dumps(params,sort_keys=True)
    current=_now().isoformat()
    with LOCK,closing(_db()) as c,c:
        active=c.execute("""SELECT * FROM historic_news_jobs WHERE
            status IN ('queued','running') ORDER BY created_at""").fetchall()
        for row in active:
            if row["params"]==label:return _public(row)
        if len(active)>=3:
            raise HTTPException(409,"At most three pending historical backfill jobs.")
        uid=str(uuid4())
        c.execute("""INSERT INTO historic_news_jobs VALUES (?,?,?,?,?,?,?,?,?)""",
                  (uid,current,current,label,"queued",0,days,"Waiting for local worker",None))
        return _public(c.execute("SELECT * FROM historic_news_jobs WHERE id=?",(uid,)).fetchone())


def get_job(job_id):
    with LOCK,closing(_db()) as c:
        row=c.execute("SELECT * FROM historic_news_jobs WHERE id=?",(job_id,)).fetchone()
    if row is None:raise HTTPException(404,"Historical news job not found.")
    return _public(row)


def list_jobs(limit=12):
    with LOCK,closing(_db()) as c:
        return [_public(r) for r in c.execute("""SELECT * FROM historic_news_jobs
            ORDER BY created_at DESC LIMIT ?""",(min(50,max(1,limit)),))]


def cancel(job_id):
    with LOCK,closing(_db()) as c,c:
        row=c.execute("SELECT * FROM historic_news_jobs WHERE id=?",(job_id,)).fetchone()
        if row is None:raise HTTPException(404,"Historical news job not found.")
        if row["status"] in ("queued","running"):
            c.execute("""UPDATE historic_news_jobs SET status='cancelled',
                        stage='Cancelled by user',updated_at=? WHERE id=?""",
                      (_now().isoformat(),job_id))
        return _public(c.execute("SELECT * FROM historic_news_jobs WHERE id=?",(job_id,)).fetchone())


def process_one(*,fetcher=None):
    """Process one archive day, so progress/cancellation survives restarts.

    The worker claims one job and releases the DB lock during HTTP download.
    Local research worker is a single process. A second worker's concurrent
    attempt is ignored via the running status and claim token.
    """
    if os.environ.get("TRADING_SIM_PUBLIC_DEMO")=="1":
        raise RuntimeError("Historical news downloads forbidden in public demo.")
    with LOCK,closing(_db()) as c,c:
        job=c.execute("""SELECT * FROM historic_news_jobs WHERE status='queued'
                      ORDER BY created_at LIMIT 1""").fetchone()
        if job is None:
            job=c.execute("""SELECT * FROM historic_news_jobs WHERE status='running'
                          ORDER BY updated_at LIMIT 1""").fetchone()
        if job is None:return None
        params=json.loads(job["params"])
        day=date.fromisoformat(params["start_date"])+timedelta(days=job["processed_days"])
        if job["processed_days"]>=job["total_days"]:
            c.execute("""UPDATE historic_news_jobs SET status='completed',
                      stage='Historical GKG range fully scanned',updated_at=?
                      WHERE id=?""",(_now().isoformat(),job["id"]))
            return get_job(job["id"])
        stamp=_now().isoformat()
        c.execute("""UPDATE historic_news_jobs SET status='running',
            stage=?,updated_at=? WHERE id=? AND status IN ('queued','running')""",
            ("Scanning GKG "+day.isoformat(),stamp,job["id"]))
    symbols=params["symbols"]
    with LOCK,closing(_db()) as c:
        covered={row[0] for row in c.execute(
            "SELECT symbol FROM historic_news_coverage WHERE news_day=?",
            (day.isoformat(),))}
    missing=[s for s in symbols if s not in covered]
    url=BASE+"/"+day.strftime("%Y%m%d")+".gkg.csv.zip"
    try:
        if missing:
            url,rows,metrics=(fetcher(day,missing) if fetcher else
                              fetch_daily(day,missing))
        else:
            rows,metrics=0,{}
        with LOCK,closing(_db()) as c,c:
            state=c.execute("SELECT status FROM historic_news_jobs WHERE id=?",
                            (job["id"],)).fetchone()
            if state is None or state["status"]!="running":
                return get_job(job["id"])
            for sym in missing:
                item=metrics[sym]
                c.execute("""INSERT OR IGNORE INTO historic_news_coverage VALUES
                    (?,?,?,?,?,?,?, ?, ?)""",
                    (sym,day.isoformat(),SOURCE,url,_archive_ready(day),
                     int(_now().timestamp()),rows,item["namesets"],item["mentions"]))
                if item["raw_tone"] is not None:
                    c.execute("""INSERT OR REPLACE INTO historic_news_tone VALUES
                        (?,?,?,?,?,?)""",(sym,day.isoformat(),item["raw_tone"],
                                         item["score"],item["namesets"],item["mentions"]))
            completed=job["processed_days"]+1
            status="completed" if completed>=job["total_days"] else "running"
            c.execute("""UPDATE historic_news_jobs SET processed_days=?,
                status=?,stage=?,error_code=NULL,updated_at=? WHERE id=?""",
                (completed,status,"Historical GKG range fully scanned" if status=="completed"
                 else "Scanned "+day.isoformat(),_now().isoformat(),job["id"]))
    except (httpx.HTTPError,OSError,ValueError,KeyError,BadZipFile,OverflowError,
            sqlite3.Error,UnicodeError,RuntimeError):
        with LOCK,closing(_db()) as c,c:
            c.execute("""UPDATE historic_news_jobs SET status='failed',
                stage='Archive unavailable or malformed: ' || ?,error_code='gkg_fetch_failed',
                updated_at=? WHERE id=? AND status='running'""",
                (day.isoformat(),_now().isoformat(),job["id"]))
    return get_job(job["id"])


def history(symbols,start_date,end_date,*,now=None):
    ids=_symbols(symbols)
    start,end,_=_period(start_date,end_date,now)
    with LOCK,closing(_db()) as c:
        placeholders=",".join("?" for _ in ids)
        coverage=c.execute(f"""SELECT c.symbol,c.news_day,c.archive_research_available_utc,
            c.rows_scanned,c.namesets,c.mentions,t.raw_tone,t.score
            FROM historic_news_coverage c
            LEFT JOIN historic_news_tone t USING(symbol,news_day)
            WHERE c.symbol IN ({placeholders}) AND c.news_day>=? AND c.news_day<=?
            ORDER BY c.news_day,c.symbol""",(*ids,start.isoformat(),end.isoformat())).fetchall()
    rows=[]
    for r in coverage:
        row=dict(r)
        row["status"]="observed_tone" if row["score"] is not None else "no_entity_match"
        rows.append(row)
    return {"source":SOURCE,"earliest_supported_date":FIRST_DATE.isoformat(),
            "requested_start":start.isoformat(),"requested_end":end.isoformat(),
            "requested_days":(end-start).days+1,"symbols":ids,
            "coverage_days_by_symbol":{s:sum(x["symbol"]==s for x in rows) for s in ids},
            "daily":rows,
            "historical_provenance":"Retrospective GDELT daily nameset tone; records were not observed live by this machine.",
            "earliest_research_use":"At least two calendar days after news day, reflecting next-day GKG publication.",
            "live_eligible":False,
            "limitations":"Article headlines and individual-article tone are unavailable in this daily aggregate. Counts and organization matching may be biased."}


def historical_score_at(symbol,decision_utc):
    """Research only. Require the exact GKG day eligible for this open.

    Daily GKG's observed publication cadence is conservatively modeled as
    D+2 at the New York 09:30 open. Missing daily coverage is NEVER filled
    from an older record, or replaced with a synthetic neutral score.
    """
    from zoneinfo import ZoneInfo
    stamp=int(decision_utc)
    decision_day=datetime.fromtimestamp(stamp,ZoneInfo("America/New_York")).date()
    relevant=(decision_day-timedelta(days=2)).isoformat()
    with LOCK,closing(_db()) as c:
        row=c.execute("""SELECT t.score FROM historic_news_coverage c
            LEFT JOIN historic_news_tone t USING(symbol,news_day)
            WHERE c.symbol=? AND c.news_day=?
            AND c.archive_research_available_utc<=?""",
            (symbol,relevant,stamp)).fetchone()
    return row["score"] if row is not None else None
