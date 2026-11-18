"""Regression checks for the research-only strategy loading affordance.

No owner strategies, trades, or research outputs are included in these checks.
"""
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"


def test_research_only_action_runs_historical_engine_instead_of_disabled_replay():
    code=(SRC/"UniverseResearch.tsx").read_text(encoding="utf-8")
    assert 'onClick={()=>void promote("research")}' in code
    assert 'createCustomPeriodStudy({spec:selectedSpec})' in code
    assert 'researchStudy={researchJob?.selection===selectedKey?researchJob.job:null}' in code
    assert 'disabled={busy||chosen.research_only}' not in code
    assert "Live engine unavailable for short or margin models" in code
    assert 'onClick={()=>void promote("simulation")}' in code
    assert 'onClick={()=>void promote("live")}' in code


def test_only_actual_work_uses_progress_cursor():
    css=(SRC/"universeResearch.css").read_text(encoding="utf-8")
    assert "cursor:wait" not in css
    assert ".ur-primary:disabled,.ur-secondary:disabled{opacity:.55;cursor:not-allowed}" in css
    assert '[aria-busy="true"]' in css
    inspector=(SRC/"TournamentStrategyInspector.tsx").read_text(encoding="utf-8")
    assert "initialJob={researchStudy}" in inspector
    runner=(SRC/"CustomStrategyAnalysis.tsx").read_text(encoding="utf-8")
    assert "if(initialJob)setJob(initialJob)" in runner
    assert "start-local.ps1" in runner
