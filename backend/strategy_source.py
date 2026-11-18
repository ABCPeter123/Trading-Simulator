"""Read-only, exact executable Python sources for portfolio-model strategies.

The UI retrieves the functions the server actually imports. It never generates
a lookalike strategy, evaluates user-submitted Python, or stores private specs.
The full source files are returned for reproducibility inside this repository.
"""
from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from typing import Any, Callable
from fastapi import HTTPException

from . import advanced_portfolio_research as advanced
from . import blended_portfolio_research as blended
from . import portfolio_research as portfolio
from . import research_optimizer
from . import tournament_strategies
from . import universe_research

ROOT = Path(__file__).resolve().parents[1]


def _module_file(fn: Callable[..., Any]) -> tuple[str, bytes]:
    """Only expose Python modules that are already part of the public engine."""
    module = inspect.getmodule(fn)
    if module is None or not getattr(module, "__file__", None):
        raise RuntimeError("Strategy entry point has no inspectable Python module.")
    path = Path(module.__file__).resolve()
    try:
        relative = path.relative_to(ROOT).as_posix()
    except ValueError:
        raise RuntimeError("Strategy source must be inside this checkout.") from None
    if not relative.startswith("backend/") or not relative.endswith(".py"):
        raise RuntimeError("Strategy source must be a public backend Python file.")
    return relative, path.read_bytes()


def _section(label: str, fn: Callable[..., Any]) -> dict:
    path, raw = _module_file(fn)
    lines, first_line = inspect.getsourcelines(fn)
    return {
        "label": label,
        "function": fn.__name__,
        "path": path,
        "first_line": first_line,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "code": "".join(lines),
    }


def _full_file(fn: Callable[..., Any]) -> dict:
    path, raw = _module_file(fn)
    return {
        "path": path,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "code": raw.decode("utf-8"),
    }


def source_for_model(spec: dict, context: str = "research") -> dict:
    """Return source for the *actual* selected runtime, never a pseudocode rewrite.

    Context matters: tournament backtesting, historical replay and daily paper
    monitoring share allocation but use different execution/accounting paths.
    """
    tournament_strategies._private()
    config = tournament_strategies.validate_spec(spec)
    if context not in ("research", "simulation", "live"):
        raise ValueError("Unsupported strategy execution context.")

    is_blend=config["model"]=="blended_portfolio"
    if is_blend and context!="research":
        raise HTTPException(422,"Blended portfolio has historical research support only.")
    advanced_model = config["model"] in advanced.MODELS
    allocation=(blended.blend_weights if is_blend else
                advanced.weights if advanced_model else portfolio._weights)
    backtest=(blended.segment if is_blend else
              advanced.segment if advanced_model else portfolio._segment)

    sections = [
        _section("Allocation decision (active Python function)", allocation),
        _section("Tournament backtest and fills (active Python function)", backtest),
        _section("Historical-return calculation (shared helper)", portfolio._returns),
        _section("Volatility calculation (shared helper)", portfolio._vol),
        _section("Performance metrics (shared helper)", research_optimizer._stats),
    ]
    files = [allocation, backtest, portfolio._weights, research_optimizer._stats]

    if context == "research":
        sections.append(_section("Tournament runner and scoring (active Python function)",
                                 universe_research.run_study))
        files.append(universe_research.run_study)
    elif context == "simulation":
        from . import portfolio_arcade
        sections.extend((
            _section("Replay model rebalance (active Python function)",
                     portfolio_arcade._rebalance_model),
            _section("Replay session advancement (active Python function)",
                     portfolio_arcade.advance),
            _section("Replay order fills (active Python function)",
                     portfolio_arcade._execute),
        ))
        files.append(portfolio_arcade._rebalance_model)
    else:
        from . import live_machine
        sections.extend((
            _section("Live portfolio recommendation logic (active Python function)",
                     live_machine._evaluate_portfolio_model),
            _section("Live evaluation scheduler (active Python function)",
                     live_machine.run_once),
        ))
        files.append(live_machine._evaluate_portfolio_model)

    full_files = []
    seen = set()
    for fn in files:
        file = _full_file(fn)
        if file["path"] not in seen:
            seen.add(file["path"])
            full_files.append(file)

    return {
        "runtime": "Python 3",
        "model": config["model"],
        "context": context,
        "entry_point": f"{allocation.__module__}.{allocation.__name__}",
        "research_execution_entry_point": f"{backtest.__module__}.{backtest.__name__}",
        "sections": sections,
        "files": full_files,
        "research_only": bool(config.get("research_only")),
        "executable": True,
    }
