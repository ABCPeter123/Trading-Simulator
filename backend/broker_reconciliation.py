"""Read-only private USD broker CSV reconciliation.

Accepts only normalized trade fields, never raw broker statement bytes. The
uploaded CSV is parsed in the owner's browser and the normalized rows are
compared against the confirmed-fill ledger in memory. Nothing is inserted,
deleted, edited or saved. Ambiguous rows are NEVER auto-matched.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from math import isfinite
from zoneinfo import ZoneInfo

from fastapi import HTTPException

NY=ZoneInfo("America/New_York")
MAX_STATEMENT_ROWS=1000
MAX_JOURNAL_ROWS=20000


def _date(value):
    if type(value) is not str or len(value)!=10:
        raise ValueError("Trade date must be YYYY-MM-DD.")
    parsed=date.fromisoformat(value)
    if parsed.isoformat()!=value:
        raise ValueError("Invalid calendar date.")
    return parsed


def _utc(value):
    if value is None:return None
    if type(value) is not str or len(value)>60:
        raise ValueError("Invalid execution timestamp.")
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Execution timestamp requires an explicit UTC offset.")
    return dt.astimezone(timezone.utc)


def _positive(value,field,allow_zero=False):
    if type(value) not in (int,float) or not isfinite(value):
        raise ValueError("Nonfinite "+field+".")
    if value<0 or (not allow_zero and value<=0) or value>1e10:
        raise ValueError("Invalid "+field+".")
    return float(value)


def normalize_row(row,index):
    if not isinstance(row,dict):
        raise ValueError("Statement contains an invalid trade row.")
    if set(row)-{"symbol","side","quantity","price","fee","currency",
                 "trade_date","executed_at","broker_ref"}:
        raise ValueError("Unsupported statement trade fields.")
    symbol=row.get("symbol")
    if (not isinstance(symbol,str) or len(symbol)>32 or not symbol
        or not all(c.isascii() and (c.isalnum() or c in "._-") for c in symbol)):
        raise ValueError("Invalid USD ticker.")
    side=row.get("side")
    if side not in ("buy","sell"):
        raise ValueError("Statement side must be buy or sell.")
    if row.get("currency","USD")!="USD":
        raise ValueError("USD-only reconciliation rejects other currencies.")
    trade_day=_date(row.get("trade_date"))
    instant=_utc(row.get("executed_at"))
    if instant and instant.astimezone(NY).date()!=trade_day:
        raise ValueError("Statement timestamp and trade date disagree in New York time.")
    broker_ref=row.get("broker_ref")
    if broker_ref is not None and (not isinstance(broker_ref,str) or len(broker_ref)>120):
        raise ValueError("Invalid broker reference.")
    return {"row":index,"symbol":symbol.lower(),"side":side,
            "quantity":_positive(row.get("quantity"),"quantity"),
            "price":_positive(row.get("price"),"price"),
            "fee":_positive(row.get("fee",0),"fee",True),
            "currency":"USD","trade_date":trade_day.isoformat(),
            "executed_at":instant.isoformat() if instant else None,
            "broker_ref":broker_ref.strip() if broker_ref else None}


def _journal_row(row):
    try:
        stamp=_utc(row["executed_at"])
        if stamp is None:raise ValueError("Missing journal timestamp.")
        symbol=str(row["asset_id"]).lower()
        currency=row["currency"]
        side=row["side"]
        if currency!="USD" or side not in ("buy","sell"):
            return None
        return {"id":str(row["id"]),"symbol":symbol,"side":side,
                "quantity":_positive(row["quantity"],"quantity"),
                "price":_positive(row["price"],"price"),
                "fee":_positive(row["fee"],"fee",True),
                "date":stamp.astimezone(NY).date().isoformat(),
                "timestamp":stamp,"broker_ref":row.get("broker_ref")}
    except (ValueError,KeyError,TypeError):
        return None


def _close(a,b,*,relative,absolute):
    return abs(a-b)<=max(absolute,relative*max(abs(a),abs(b)))


def _field_match(stmt,fill):
    return (stmt["symbol"]==fill["symbol"] and stmt["side"]==fill["side"]
            and stmt["trade_date"]==fill["date"]
            and _close(stmt["quantity"],fill["quantity"],relative=1e-6,absolute=1e-7)
            and _close(stmt["price"],fill["price"],relative=.005,absolute=.05))


def _differences(stmt,fill):
    differences=[]
    for field in ("symbol","side"):
        if stmt[field]!=fill[field]:differences.append(field)
    if stmt["trade_date"]!=fill["date"]:differences.append("trade_date")
    if not _close(stmt["quantity"],fill["quantity"],relative=1e-6,absolute=1e-7):
        differences.append("quantity")
    if not _close(stmt["price"],fill["price"],relative=.00001,absolute=.01):
        differences.append("price")
    if not _close(stmt["fee"],fill["fee"],relative=.00001,absolute=.01):
        differences.append("fee")
    return differences


def reconcile(statement,journal):
    """Never calls a broker or modifies the confirmed journal.

    Explicit broker references take precedence, but references shared by
    multiple partial trades are marked ambiguous. Otherwise a conservative
    price/quantity/date candidate match is attempted with no arbitrary
    tie-breaking.
    """
    if not isinstance(statement,list) or not 1<=len(statement)<=MAX_STATEMENT_ROWS:
        raise HTTPException(422,"Supply 1-1000 normalized statement trades.")
    if not isinstance(journal,list) or len(journal)>MAX_JOURNAL_ROWS:
        raise HTTPException(422,"Confirmed journal is too large to reconcile.")
    try:
        parsed=[normalize_row(row,index+1) for index,row in enumerate(statement)]
    except (ValueError,TypeError) as exc:
        raise HTTPException(422,str(exc)) from None
    recorded=[item for r in journal if (item:=_journal_row(r)) is not None]
    by_ref=defaultdict(list)
    by_fields=defaultdict(list)
    for f in recorded:
        if f["broker_ref"]:by_ref[f["broker_ref"]].append(f)
        by_fields[(f["symbol"],f["side"],f["date"])].append(f)
    used=set();reviews=[]
    for source in parsed:
        ref=source["broker_ref"]
        candidate=None
        match_type=None
        status="not_in_journal"
        options=by_ref.get(ref,[]) if ref else []
        if ref and len(options)>1:
            status="ambiguous_broker_reference"
        elif len(options)==1:
            candidate=options[0]
            match_type="broker_reference"
        else:
            matches=[f for f in by_fields[(source["symbol"],source["side"],
                                          source["trade_date"])] if _field_match(source,f)]
            if len(matches)>1:
                status="ambiguous_field_match"
            elif len(matches)==1:
                candidate=matches[0]
                match_type="symbol_side_date_quantity_price"
        differences=[]
        match_id=None
        if candidate is not None:
            match_id=candidate["id"]
            if match_id in used:
                status="duplicate_statement_row"
            else:
                used.add(match_id)
                differences=_differences(source,candidate)
                status="matched_with_differences" if differences else "matched"
        reviews.append({
            "statement_row":source["row"],
            "symbol":source["symbol"],"side":source["side"],
            "trade_date":source["trade_date"],
            "status":status,"matched_fill_id":match_id,
            "match_type":match_type if candidate else None,
            "differences":differences,
            "statement_price":source["price"],"statement_quantity":source["quantity"],
            "statement_fee":source["fee"],
            "journal_price":candidate["price"] if candidate else None,
            "journal_quantity":candidate["quantity"] if candidate else None,
            "journal_fee":candidate["fee"] if candidate else None,
        })
    start=min(source["trade_date"] for source in parsed)
    stop=max(source["trade_date"] for source in parsed)
    # Partial exports can omit journal rows. Avoid claiming these are missing
    # broker trades; report only "not present in this import date range".
    absent=[{"fill_id":f["id"],"symbol":f["symbol"],"side":f["side"],
             "trade_date":f["date"]}
            for f in recorded if start<=f["date"]<=stop and f["id"] not in used]
    count=lambda status:sum(x["status"]==status for x in reviews)
    return {
        "read_only":True,"import_persisted":False,"currency":"USD",
        "date_range":{"start":start,"end":stop},
        "summary":{
            "statement_rows":len(parsed),"journal_rows_in_date_range":
                sum(start<=f["date"]<=stop for f in recorded),
            "matched":count("matched"),"matched_with_differences":count("matched_with_differences"),
            "not_in_journal":count("not_in_journal"),
            "ambiguous":count("ambiguous_broker_reference")+count("ambiguous_field_match"),
            "duplicate_statement_rows":count("duplicate_statement_row"),
            "journal_not_in_import":len(absent),
        },
        "reviews":reviews,"journal_not_in_import":absent,
        "limitations":"Read-only comparison of normalized rows. Unlisted exports are not proof of missing broker executions. No journal edits.",
    }
