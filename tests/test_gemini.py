"""Gemini provider: schema conversion and the tool loop, against simulated Gemini REST responses (no key, no network)."""
import os

os.environ["MARSWALK_SKIP_WARM"] = "1"

from flight_controller import agent  # noqa: E402


def test_gemini_tool_schemas_are_openapi_subset():
    decls = agent.gemini_tools()[0]["functionDeclarations"]
    names = {d["name"] for d in decls}
    assert {"plan_route", "replan", "search_docs", "get_space_weather", "find_similar_ground"} <= names

    def no_additional(x):
        if isinstance(x, dict):
            return "additionalProperties" not in x and all(no_additional(v) for v in x.values())
        if isinstance(x, list):
            return all(no_additional(v) for v in x)
        return True
    assert all(no_additional(d) for d in decls)
    assert "parameters" not in next(d for d in decls if d["name"] == "get_space_weather")   # no-arg tool


def test_gemini_loop_runs_tools_and_verifies(monkeypatch):
    """Turn 1: model calls plan_route. Turn 2: model answers with a number copied from the tool result."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-test-key")
    seen = []

    def fake_post(body):
        seen.append(body)
        if len(seen) == 1:
            return {"candidates": [{"content": {"role": "model", "parts": [
                {"functionCall": {"name": "plan_route", "args": {"targets": ["seitah"], "objective": "safest"}}}]}}]}
        # find the distance the planner returned, and quote it like a model would
        result = body["contents"][-1]["parts"][0]["functionResponse"]["response"]["result"]
        km = result["routes"][0]["distance_km"]
        return {"candidates": [{"content": {"role": "model", "parts": [{"text": f"Safest route to Seitah: {km} km."}]}}]}

    assert agent.provider() == "gemini"
    out = agent.ask([{"role": "user", "content": "Safest route to Seitah?"}], post=fake_post)
    assert out["provider"] == "gemini" and out["mode"] == "live"
    assert out["tool_calls"][0]["name"] == "plan_route" and out["routes"]
    assert out["verification"]["passed"] and out["verification"]["verified_count"] >= 1
    assert "functionDeclarations" in seen[0]["tools"][0] and seen[0]["systemInstruction"]["parts"][0]["text"]


def test_gemini_invented_number_is_caught(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "SYNTHETIC-test-key")
    replies = iter([{"candidates": [{"content": {"role": "model", "parts": [{"text": "You will use 0.9 kg of O2."}]}}]}] * 2)
    out = agent.ask([{"role": "user", "content": "How much oxygen?"}], post=lambda body: next(replies))
    assert not out["verification"]["passed"] and out["verification"]["unverified"][0]["text"].startswith("0.9 kg")


def test_no_key_falls_back_to_offline(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert agent.provider() == "offline"
