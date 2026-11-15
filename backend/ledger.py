"""SQLite-backed local long-only paper execution. Cash ledger uses Decimal."""
from __future__ import annotations

import os
import sqlite3
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from threading import RLock
from uuid import uuid4
from datetime import datetime, timezone
from fastapi import HTTPException
from .assets import INSTRUMENTS, get_instrument

START_CASH = Decimal("100000.00")
DB_PATH = Path(os.environ.get("TRADING_SIM_DB", Path(__file__).resolve().parent.parent / "data" / "trading.sqlite3"))
DB_LOCK = RLock()

def database() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("""CREATE TABLE IF NOT EXISTS fills (
        id TEXT PRIMARY KEY, asset_id TEXT NOT NULL, side TEXT NOT NULL,
        quantity TEXT NOT NULL, price TEXT NOT NULL, fee TEXT NOT NULL,
        source TEXT NOT NULL, quote_time TEXT NOT NULL, created_at TEXT NOT NULL)""")
    return connection

def dec(value: object) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise HTTPException(400, detail="Invalid numeric input.") from exc
    if not result.is_finite():
        raise HTTPException(400, detail="Order numbers must be finite.")
    return result

def positive_quantity(value: object, whole: bool = False) -> Decimal:
    amount = dec(value)
    if amount <= 0 or amount > Decimal("100000000"):
        raise HTTPException(400, detail="Quantity must be positive and at most 100 million.")
    if amount.as_tuple().exponent < -8:
        raise HTTPException(400, detail="At most eight decimal places are supported.")
    if whole and amount != amount.to_integral_value():
        raise HTTPException(400, detail="Whole shares/contracts required.")
    return amount

def fee_for(instrument_kind: str, quantity: Decimal, price: Decimal) -> Decimal:
    notional = quantity * price
    if instrument_kind in ("Stocks", "ETFs"):
        return max(Decimal("1"), quantity * Decimal("0.005")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    if instrument_kind == "Crypto":
        return (notional * Decimal("0.006")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    if instrument_kind == "Forex":
        return (notional * Decimal("0.0002")).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)
    raise HTTPException(422, detail="Execution model unavailable for this instrument.")

def modeled_fill(side: str, quote_data: dict, slippage_bps: Decimal = Decimal("2")) -> Decimal:
    """Bid/ask if exchange provides it; otherwise midpoint proxy ± modeled half-spread.
    Additional 2 bps slippage. Does NOT claim actual queue, depth, or executable fills.
    """
    reference = dec(quote_data["ask" if side == "buy" else "bid"] or quote_data["price"])
    spread = dec(quote_data["spread_bps"]) / Decimal(20000) if quote_data["bid"] is None else Decimal(0)
    impact = spread + slippage_bps / Decimal(10000)
    return reference * (1 + impact if side == "buy" else 1 - impact)

def _state(rows: list[sqlite3.Row]) -> tuple[Decimal, dict[str, tuple[Decimal, Decimal]], Decimal]:
    cash = START_CASH
    holdings: dict[str, tuple[Decimal, Decimal]] = {}
    realized = Decimal(0)
    for row in rows:
        qty, price, fee = dec(row["quantity"]), dec(row["price"]), dec(row["fee"])
        old_qty, avg_cost = holdings.get(row["asset_id"], (Decimal(0), Decimal(0)))
        if row["side"] == "buy":
            cash -= qty * price + fee
            new_qty = old_qty + qty
            holdings[row["asset_id"]] = (new_qty, (old_qty * avg_cost + qty * price + fee) / new_qty)
        else:
            cash += qty * price - fee
            realized += qty * (price - avg_cost) - fee
            new_qty = old_qty - qty
            holdings[row["asset_id"]] = (new_qty, avg_cost if new_qty > 0 else Decimal(0))
    return cash, holdings, realized

def account_snapshot(quotes: dict[str, dict] | None = None) -> dict:
    with DB_LOCK, database() as db:
        rows = db.execute("SELECT * FROM fills ORDER BY rowid ASC").fetchall()
    cash, holdings, realized = _state(rows)
    positions = []
    mark_total = Decimal(0)
    unrealized = Decimal(0)
    for asset_id, (qty, avg) in holdings.items():
        if qty <= 0: continue
        quote_data = (quotes or {}).get(asset_id)
        mark = dec(quote_data["price"]) if quote_data else None
        value = mark * qty if mark is not None else None
        pnl = (mark - avg) * qty if mark is not None else None
        if value is not None:
            mark_total += value
            unrealized += pnl
        positions.append({
            "asset_id": asset_id, "quantity": float(qty), "average_cost": float(avg),
            "mark": float(mark) if mark is not None else None, "market_value": float(value) if value is not None else None,
            "unrealized_pnl": float(pnl) if pnl is not None else None,
        })
    return {
        "cash": float(cash),
        "equity": float(cash + mark_total) if all(p["mark"] is not None for p in positions) else None,
        "realized_pnl": float(realized),
        "unrealized_pnl": float(unrealized) if all(p["mark"] is not None for p in positions) else None,
        "positions": positions,
        "fills": [{**dict(row), "quantity": float(row["quantity"]), "price": float(row["price"]), "fee": float(row["fee"])} for row in reversed(rows)],
        "has_unpriced_positions": any(p["mark"] is None for p in positions),
    }

def submit_order(asset_id: str, side: str, quantity: object, quote_data: dict) -> dict:
    instrument = get_instrument(asset_id)
    if not instrument.tradable or instrument.currency != "USD":
        raise HTTPException(422, detail="This instrument cannot be traded in the current USD cash model.")
    if not quote_data["tradable"]:
        raise HTTPException(409, detail=quote_data.get("block_reason") or "Market quote is not executable.")
    if side not in ("buy", "sell"):
        raise HTTPException(400, detail="Unsupported order side.")
    qty = positive_quantity(quantity, whole=instrument.kind in ("Stocks", "ETFs"))
    price = modeled_fill(side, quote_data)
    if price <= 0: raise HTTPException(422, detail="Invalid modeled fill price.")
    fee = fee_for(instrument.kind, qty, price)
    now = datetime.now(timezone.utc).isoformat()
    new_id = str(uuid4())
    with DB_LOCK, database() as db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute("SELECT * FROM fills ORDER BY rowid ASC").fetchall()
        cash, holdings, _ = _state(rows)
        if side == "buy" and qty * price + fee > cash:
            raise HTTPException(409, detail="Insufficient cash including modeled fees.")
        if side == "sell" and qty > holdings.get(asset_id, (Decimal(0), Decimal(0)))[0]:
            raise HTTPException(409, detail="Insufficient long position. Short sales are not available.")
        db.execute(
            "INSERT INTO fills VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, asset_id, side, str(qty), str(price), str(fee), quote_data["source"], quote_data["timestamp"], now),
        )
        db.commit()
    return {
        "id": new_id, "asset_id": asset_id, "side": side, "quantity": float(qty),
        "price": float(price), "fee": float(fee), "created_at": now,
        "source": quote_data["source"], "quote_time": quote_data["timestamp"],
    }

def reset_account() -> None:
    with DB_LOCK, database() as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("DELETE FROM fills")
        db.commit()
