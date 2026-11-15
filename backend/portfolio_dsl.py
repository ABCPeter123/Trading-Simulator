"""Safe cross-asset strategy statements, compiled using the existing DSL.

Syntax:
    WHEN SPY SMA(10) CROSSES ABOVE SMA(30) BUY 25% QQQ
    WHEN QQQ RSI(14) ABOVE 70 SELL 100% QQQ

This says WHICH SYMBOL triggers a signal and WHICH SYMBOL receives the trade.
No eval, Python code, or access to hidden future candles.
"""
from dataclasses import dataclass
import re

from fastapi import HTTPException
from .arcade_dsl import Rule, compile_rules, MAX_CODE, MAX_RULES


_LINE = re.compile(
    r"^WHEN\s+([A-Za-z0-9_.-]+)\s+(.*?)\s+(BUY|SELL)\s+"
    r"(\d{1,3}(?:\.\d{1,2})?)%\s+([A-Za-z0-9_.-]+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PortfolioRule:
    signal_id: str
    target_id: str
    rule: Rule


def compile_portfolio_rules(code: str, allowed: set[str]) -> list[PortfolioRule]:
    if len(code) > MAX_CODE:
        raise HTTPException(422, detail=f"Maximum strategy length is {MAX_CODE} characters.")
    result = []
    for line_num, raw in enumerate(code.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _LINE.fullmatch(stripped)
        if match is None:
            raise HTTPException(
                422, detail=f"Line {line_num}: use WHEN SPY SMA(10) ABOVE SMA(30) BUY 25% QQQ."
            )
        signal_id, test, side, percent, target_id = match.groups()
        signal_id, target_id = signal_id.lower(), target_id.lower()
        if signal_id not in allowed or target_id not in allowed:
            raise HTTPException(422, detail=f"Line {line_num}: both symbols must be in the game basket.")
        rule = compile_rules(f"WHEN {test} {side} {percent}%")[0]
        result.append(PortfolioRule(signal_id, target_id, rule))
        if len(result) > MAX_RULES:
            raise HTTPException(422, detail=f"Maximum {MAX_RULES} rules.")
    return result
