"""Small, deterministic strategy language. No eval/exec, imports, or Python code.

Grammar (one WHEN rule per line):
  WHEN SMA(10) CROSSES ABOVE SMA(30) BUY 25%
  WHEN SMA(10) CROSSES BELOW SMA(30) SELL 100%
  WHEN RSI(14) BELOW 30 BUY 25%
  WHEN PRICE ABOVE SMA(20) SELL 50%
All conditions are edge-triggered at the visible bar CLOSE; execution occurs
no earlier than the following bar OPEN. BUY % means available cash and SELL %
means held units, calculated when the order is filled.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
import re

from fastapi import HTTPException

MAX_CODE = 1800
MAX_RULES = 12
_EXPRESSION = r"(?:PRICE|SMA\(\d{1,3}\)|RSI\(\d{1,2}\)|\d+(?:\.\d+)?)"
_RULE = re.compile(
    rf"^WHEN\s+({_EXPRESSION})\s+(CROSSES\s+ABOVE|CROSSES\s+BELOW|ABOVE|BELOW)\s+"
    rf"({_EXPRESSION})\s+(BUY|SELL)\s+(\d{{1,3}}(?:\.\d{{1,2}})?)%$",
    re.IGNORECASE,
)

@dataclass(frozen=True)
class Rule:
    left: str
    operator: str
    right: str
    side: str
    percent: float
    line: int

    def to_dict(self) -> dict:
        return asdict(self)


def compile_rules(program: str) -> list[Rule]:
    if len(program) > MAX_CODE:
        raise HTTPException(422, detail=f"Strategy exceeds {MAX_CODE} characters.")
    rules: list[Rule] = []
    for lineno, raw in enumerate(program.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _RULE.fullmatch(line)
        if not match:
            raise HTTPException(
                422, detail=f"Line {lineno}: invalid rule. Example: WHEN SMA(10) CROSSES ABOVE SMA(30) BUY 25%"
            )
        left, operation, right, side, pct = match.groups()
        left, right = left.upper(), right.upper()
        pct_float = float(pct)
        if not 0 < pct_float <= 100:
            raise HTTPException(422, detail=f"Line {lineno}: order size must be between 0 and 100%.")
        operation = " ".join(operation.upper().split())
        for expr in (left, right):
            period = re.fullmatch(r"(?:SMA|RSI)\((\d+)\)", expr)
            if period and not 2 <= int(period.group(1)) <= 100:
                raise HTTPException(422, detail=f"Line {lineno}: indicator period must be from 2 to 100.")
        rules.append(Rule(left, operation, right, side.lower(), pct_float, lineno))
        if len(rules) > MAX_RULES:
            raise HTTPException(422, detail=f"Only {MAX_RULES} strategy rules are supported.")
    return rules


def indicator(expr: str, bars: list[dict], index: int) -> float | None:
    if index < 0:
        return None
    if expr == "PRICE":
        return float(bars[index]["close"])
    if expr.startswith("SMA("):
        period = int(expr[4:-1])
        if index + 1 < period:
            return None
        return sum(float(bar["close"]) for bar in bars[index-period+1:index+1]) / period
    if expr.startswith("RSI("):
        period = int(expr[4:-1])
        if index < period:
            return None
        differences = [
            float(bars[j]["close"]) - float(bars[j-1]["close"])
            for j in range(index - period + 1, index + 1)
        ]
        gain = sum(max(d, 0.0) for d in differences) / period
        loss = sum(max(-d, 0.0) for d in differences) / period
        if gain == loss == 0:
            return 50.0
        if loss == 0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + gain / loss)
    return float(expr)


def matches(rule: Rule, bars: list[dict], index: int) -> bool:
    if index < 1:
        return False
    a0 = indicator(rule.left, bars, index - 1)
    b0 = indicator(rule.right, bars, index - 1)
    a1 = indicator(rule.left, bars, index)
    b1 = indicator(rule.right, bars, index)
    if any(value is None or not isfinite(value) for value in (a0, b0, a1, b1)):
        return False
    # Explicit CROSSES and short ABOVE/BELOW mean edge triggers, not
    # a buy on every candle spent above a threshold.
    if rule.operator.endswith("ABOVE"):
        return a0 <= b0 and a1 > b1
    return a0 >= b0 and a1 < b1


EXAMPLES = [
    {"title": "Moving average crossover", "code":
     "WHEN SMA(10) CROSSES ABOVE SMA(30) BUY 50%\nWHEN SMA(10) CROSSES BELOW SMA(30) SELL 100%"},
    {"title": "RSI recovery", "code":
     "WHEN RSI(14) BELOW 30 BUY 25%\nWHEN RSI(14) ABOVE 70 SELL 100%"},
    {"title": "Price vs trend", "code":
     "WHEN PRICE ABOVE SMA(20) BUY 20%\nWHEN PRICE BELOW SMA(20) SELL 100%"},
]
