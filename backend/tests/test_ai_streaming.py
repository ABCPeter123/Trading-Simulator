"""Synthetic tests for local streaming preview, validation and cancellation.

These tests contain no real portfolio records, remote API calls, or models.
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from backend import ai_assistant as ai
from backend.main import app


def parse_event(text):
    result = []
    for block in text.split("\n\n"):
        if not block:
            continue
        event = next((s[7:].strip() for s in block.splitlines()
                      if s.startswith("event: ")), None)
        data = next((s[6:].strip() for s in block.splitlines()
                     if s.startswith("data: ")), None)
        if event and data:
            result.append((event, json.loads(data)))
    return result


@pytest.fixture
def fake_streaming(monkeypatch):
    monkeypatch.setenv("TRADING_SIM_AI_PROVIDER", "llama_cpp")
    monkeypatch.setenv("TRADING_SIM_AI_MODEL", "Qwen3.5-4B-Q4_K_M.gguf")
    monkeypatch.setenv("TRADING_SIM_AI_MODELS", "Qwen3.5-4B-Q4_K_M.gguf")
    monkeypatch.setenv("TRADING_SIM_AI_MAX_OUTPUT_TOKENS", "384")
    monkeypatch.setattr(ai, "game_context", lambda mode, run_id: {
        "mode": mode,
        "symbols": ["synthetic-a"], "period": "synthetic",
        "observed_start": "2024-01-01", "observed_end": "2024-01-20",
        "observed_steps": 20,
        "summary": {"total_return_pct": 2.5, "benchmark_return_pct": 3.0},
        "risk": {"stop_loss_pct": 5}, "positions": [],
        "saved_strategy_untrusted": "SYNTHETIC example",
        "observed_curve_samples": [],
        "most_recent_executions": [],
    })
    called = {"requests": [], "closed": 0}
    # Include malicious/unvalidated strategy in raw model JSON. It must never
    # be sent to the browser, not even as partial raw text.
    raw = json.dumps({
        "answer": "Observed return was 2.5% against a 3.0% benchmark.",
        "strategy": "__import__('os').system('unsafe')"
    })
    chunks = [raw[i:i+8] for i in range(0, len(raw), 8)]
    class Upstream:
        status_code = 200
        async def __aenter__(self): return self
        async def __aexit__(self, *args): called["closed"] += 1
        async def aiter_lines(self):
            for text in chunks:
                yield "data: " + json.dumps({"choices": [{"delta": {"content": text}}]})
            yield 'data: {"usage":{"prompt_tokens":94,"completion_tokens":31},"choices":[]}'
            yield "data: [DONE]"
    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def stream(self, method, url, json):
            assert method == "POST"
            assert url == ai.LLAMA_CPP_CHAT_URL
            called["requests"].append(json)
            return Upstream()
    monkeypatch.setattr(ai.httpx, "AsyncClient", FakeClient)
    return called


def test_preview_only_exposes_decoded_answer_not_raw_strategy():
    raw = '{"answer": "Return was 2.5% \\u0026 drawdown -3%","strategy":"PRIVATE_DO_NOT_SHOW"}'
    assert ai._visible_answer_preview(raw) == "Return was 2.5% & drawdown -3%"
    assert ai._visible_answer_preview('{"strategy":"PRIVATE_DO_NOT_SHOW","answer":"Observed"}') == ""
    assert ai._visible_answer_preview('{"strategy":"PRIVATE_DO_NOT_SHOW"}') == ""
    assert ai._visible_answer_preview('{"answer":"unfinished \\') == "unfinished "
    assert ai._visible_answer_preview("random <think>private</think>") == ""


def test_stream_endpoint_sends_only_preview_and_validated_final(fake_streaming):
    response = TestClient(app).post("/api/ai/ask/stream", json={
        "mode": "single", "run_id": "synthetic-only",
        "question": "Explain observed performance",
    })
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-store"
    events = parse_event(response.text)
    assert events[0][0] == "status"
    assert any(event == "progress" for event, _ in events)
    assert events[-1][0] == "done"
    assert "unsafe" not in response.text
    assert all("strategy" not in payload for event, payload in events
               if event != "done")
    final = events[-1][1]
    assert final["answer"] == "Observed return was 2.5% against a 3.0% benchmark."
    assert final["proposed_strategy"] is None
    assert final["proposal_validated"] is False
    assert final["applied"] is False
    assert final["metrics"]["prompt_tokens"] == 94
    assert final["metrics"]["completion_tokens"] == 31
    assert final["metrics"]["first_output_ms"] is not None
    assert final["metrics"]["total_ms"] >= final["metrics"]["first_output_ms"]
    assert fake_streaming["closed"] == 1
    request = fake_streaming["requests"][0]
    assert request["model"] == "Qwen3.5-4B-Q4_K_M"
    assert request["stream"] is True
    assert request["max_tokens"] == 384
    assert request["cache_prompt"] is True
    assert request["stream_options"] == {"include_usage": True}
    assert request["chat_template_kwargs"] == {"enable_thinking": False}
    assert "synthetic-only" not in str(request)


def test_stream_closes_upstream_when_browser_aborts(fake_streaming):
    async def collect_partial():
        generator = ai.stream_advice("single", "synthetic-run", "Explain my return")
        first = await anext(generator)
        assert "event: status" in first
        while True:
            event = await anext(generator)
            if "event: progress" in event:
                break
        await generator.aclose()
    asyncio.run(collect_partial())
    assert fake_streaming["closed"] == 1


def test_stream_rejects_remote_provider(monkeypatch):
    monkeypatch.setenv("TRADING_SIM_AI_PROVIDER", "off")
    response = TestClient(app).post("/api/ai/ask/stream", json={
        "mode": "single", "run_id": "synthetic",
        "question": "Analyze performance",
    })
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/json")


def test_invalid_or_missing_model_is_not_started(monkeypatch):
    monkeypatch.setenv("TRADING_SIM_AI_PROVIDER", "llama_cpp")
    monkeypatch.setenv("TRADING_SIM_AI_MODEL", "Qwen3.5-4B-Q4_K_M.gguf")
    monkeypatch.setenv("TRADING_SIM_AI_MODELS", "Qwen3.5-4B-Q4_K_M.gguf")
    # The generator cannot return unvalidated answer or strategy.
    with pytest.raises(Exception):
        ai.selected_local_model("../../../models/private/model.gguf")
