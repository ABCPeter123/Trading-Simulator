"""Regression checks for English/Simplified Chinese UI coverage.

No new dependencies. Invoked from the existing frontend GitHub Action.
"""
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
src = (ROOT / "src" / "i18n.tsx").read_text(encoding="utf-8")
table = src.split("const zh: Record<string, string> = {", 1)[1].split("\n};", 1)[0]
entries = re.findall(r'^\s*"((?:[^"\\]|\\.)+)":\s*"((?:[^"\\]|\\.)*)",?$', table, re.M)
translations = {key for key, _ in entries}
assert len(entries) == len(translations), "Duplicate keys in localization catalog"
assert len(translations) >= 300, "Unexpectedly incomplete Simplified Chinese catalog"
missing: dict[str, list[str]] = {}
for relative in ["MarketDesk.tsx", "StrategyLibrary.tsx", "TradingArcade.tsx", "PortfolioArcade.tsx", "VisualStrategyBuilder.tsx", "StrategyAnalytics.tsx", "AIAssistant.tsx", "WorkspaceTabs.tsx", "StochasticResearch.tsx"]:
    file = ROOT / "src" / relative
    content = file.read_text(encoding="utf-8")
    assert 'useI18n' in content, f"Missing locale hook in {relative}"
    # Match direct t("...") calls while avoiding setState(...) suffixes.
    used = set(re.findall(r'(?<![A-Za-z0-9_])t\("([^"]+)"\)', content))
    keys = sorted(key for key in used if key not in translations)
    if keys:
        missing[relative] = keys
if missing:
    print("Missing translation keys:", missing, file=sys.stderr)
    sys.exit(1)
root = (ROOT / "src" / "main.tsx").read_text(encoding="utf-8")
assert "<I18nProvider>" in root and "<LanguageSwitcher/>" in root
assert 'localStorage.setItem(STORAGE_KEY' in src, "Locale choice is not persistent"
assert 'document.documentElement.lang = locale' in src, "HTML language not updated"
print(f"Localization check passed: {len(translations)} translated labels, all simulator workspaces wired.")
