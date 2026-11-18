"""Static UI contract: model descriptions remain complete and do not expose source panes.

The strategy algorithms and all owner data remain unchanged. This test reads only
public application source and compares it with registered public model families.
"""
from pathlib import Path
import re

from backend import advanced_portfolio_research as advanced
from backend import portfolio_research as standard

ROOT = Path(__file__).resolve().parents[2]
NARRATIVES = ROOT / "src" / "strategyNarratives.ts"
INSPECTOR = ROOT / "src" / "TournamentStrategyInspector.tsx"


def test_every_registered_model_has_a_bilingual_narrative():
    source = NARRATIVES.read_text(encoding="utf-8")
    documented = set(re.findall(
        r'^  ([a-z_]+):\{\s*\n\s*name:b\(', source, flags=re.MULTILINE
    ))
    assert documented == set(standard.MODELS) | set(advanced.MODELS)
    for model in documented:
        block = source.split("  " + model + ":{", 1)[1].split("\n  },", 1)[0]
        assert "goal:b(" in block
        assert "steps:[" in block
        assert "caveat:b(" in block
        assert block.count("      s(") >= 4
        assert re.search(r'name:b\("[^"]+","[^"]+"\)', block)


def test_inspector_uses_explanations_instead_of_source_code_panels():
    ui = INSPECTOR.read_text(encoding="utf-8")
    assert "MODEL_EXPLANATIONS" in ui
    assert "explanationText(" in ui
    assert "getTournamentPythonSource" not in ui
    assert "PythonStrategySource" not in ui
    assert "<pre>" not in ui
    assert "Copy exact Python" not in ui
    assert "Versioned strategy parameters (JSON)" not in ui
    assert "locale" in ui
