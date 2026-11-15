"""Flight Controller: a tool-use loop over the planner, with number verification.

Providers (env LLM_PROVIDER, default "anthropic"):
  anthropic  Claude via the Anthropic SDK; model env CLAUDE_MODEL (default claude-sonnet-5-5); needs ANTHROPIC_API_KEY.
  gemini     Google Gemini via the REST API (no extra dependency); model env GEMINI_MODEL (default gemini-2.5-flash);
             needs GEMINI_API_KEY (free tier available from Google AI Studio).
Whatever the provider, the same tools run and the same verifier checks every number in the answer.
Without a key the agent runs in OFFLINE mode: a deterministic parser and a templated answer built
only from tool results, clearly labelled, so the demo never depends on a key.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

from flight_controller import tools, verifier

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
SYSTEM = (Path(__file__).parent / "prompts" / "system.md").read_text(encoding="utf-8")
MAX_STEPS = 8


def _client():
    try:
        import anthropic

        if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN") or os.getenv("ANTHROPIC_PROFILE")):
            return None
        return anthropic.Anthropic()
    except Exception:
        return None


def _create(client, messages: list[dict], system: str):
    # Server-side fallback: on a safety-classifier decline the API re-runs the request on a
    # fallback model chosen by refusal category (beta server-side-fallback-2026-07-01).
    return client.beta.messages.create(
        model=MODEL, max_tokens=16000, system=system, tools=tools.TOOLS, messages=messages,
        betas=["server-side-fallback-2026-07-01"], fallbacks="default",
    )


def _loop(client, messages: list[dict], ctx: dict, system: str) -> tuple[str, list]:
    calls = []
    for _ in range(MAX_STEPS):
        resp = _create(client, messages, system)
        if resp.stop_reason == "refusal":
            return "I can't help with that request.", calls
        messages.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in resp.content]})
        uses = [b for b in resp.content if b.type == "tool_use"]
        if resp.stop_reason != "tool_use" or not uses:
            return "".join(b.text for b in resp.content if b.type == "text").strip(), calls
        results = []
        for u in uses:
            try:
                out = tools.run_tool(u.name, dict(u.input), ctx)
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": tools.dumps(out)})
                calls.append({"name": u.name, "input": dict(u.input), "output": out})
            except Exception as e:  # tool errors go back to the model, never swallowed
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": f"error: {e}", "is_error": True})
                calls.append({"name": u.name, "input": dict(u.input), "error": str(e)})
        messages.append({"role": "user", "content": results})
    return "I ran out of planning steps; please narrow the request.", calls


# --- Gemini (REST, function calling) -----------------------------------------------------------

def _gemini_schema(schema: dict) -> dict | None:
    """Anthropic JSON schema -> Gemini OpenAPI subset (no additionalProperties; empty objects omitted)."""
    def clean(x):
        if isinstance(x, dict):
            return {k: clean(v) for k, v in x.items() if k != "additionalProperties"}
        if isinstance(x, list):
            return [clean(v) for v in x]
        return x
    out = clean(schema)
    return out if out.get("properties") else None


def gemini_tools() -> list[dict]:
    decls = []
    for t in tools.TOOLS:
        d = {"name": t["name"], "description": t["description"]}
        params = _gemini_schema(t["input_schema"])
        if params:
            d["parameters"] = params
        decls.append(d)
    return [{"functionDeclarations": decls}]


def _gemini_post(body: dict) -> dict:
    req = urllib.request.Request(GEMINI_URL.format(model=GEMINI_MODEL), data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"content-type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))


def _gemini_loop(contents: list[dict], ctx: dict, system: str, post=_gemini_post) -> tuple[str, list]:
    calls = []
    for _ in range(MAX_STEPS):
        resp = post({"systemInstruction": {"parts": [{"text": system}]}, "contents": contents, "tools": gemini_tools()})
        cands = resp.get("candidates") or []
        if not cands or "content" not in cands[0]:
            return "I can't help with that request.", calls
        content = cands[0]["content"]
        parts = content.get("parts", [])
        contents.append({"role": "model", "parts": parts})
        fcalls = [p["functionCall"] for p in parts if "functionCall" in p]
        if not fcalls:
            return "".join(p.get("text", "") for p in parts).strip(), calls
        responses = []
        for fc in fcalls:
            name, args = fc["name"], dict(fc.get("args") or {})
            try:
                out = tools.run_tool(name, args, ctx)
                responses.append({"functionResponse": {"name": name, "response": {"result": json.loads(tools.dumps(out))}}})
                calls.append({"name": name, "input": args, "output": out})
            except Exception as e:  # tool errors go back to the model, never swallowed
                responses.append({"functionResponse": {"name": name, "response": {"error": str(e)}}})
                calls.append({"name": name, "input": args, "error": str(e)})
        contents.append({"role": "user", "parts": responses})
    return "I ran out of planning steps; please narrow the request.", calls


def provider() -> str:
    """Which language model answers: 'gemini', 'anthropic' or 'offline' (no key)."""
    want = os.getenv("LLM_PROVIDER", "anthropic").lower()
    if want == "gemini":
        return "gemini" if os.getenv("GEMINI_API_KEY") else "offline"
    return "anthropic" if _client() is not None else "offline"


def ask(history: list[dict], post=None) -> dict:
    """history: [{role, content}] plain-text chat. Returns the /assistant response shape."""
    prov = provider()
    if prov == "offline":
        return offline_answer(history[-1]["content"])
    ctx: dict = {}
    if prov == "gemini":
        contents = [{"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in history]

        def run(fix: str | None = None):
            if fix:
                contents.append({"role": "user", "parts": [{"text": fix}]})
            return _gemini_loop(contents, ctx, SYSTEM, post or _gemini_post)
        model_name = GEMINI_MODEL
    else:
        client = _client()
        messages = [{"role": m["role"], "content": m["content"]} for m in history]

        def run(fix: str | None = None):
            if fix:
                messages.append({"role": "user", "content": fix})
            return _loop(client, messages, ctx, SYSTEM)
        model_name = MODEL
    answer, calls = run()
    check = verifier.check(answer, [[c.get("input"), c.get("output")] for c in calls])
    missing = _missing_citations(answer, ctx)
    if not check["passed"] or missing:
        fix = ("Your answer contains numbers that do not match any tool result from this turn: "
               + ", ".join(u["text"] for u in check["unverified"])
               + (". It also cites passages that were not retrieved: " + ", ".join(missing) if missing else "")
               + ". Rewrite the answer using only numbers copied from tool results (call tools again if needed) "
                 "and only citations you retrieved.")
        answer2, calls2 = run(fix)
        calls += calls2
        check = verifier.check(answer2, [[c.get("input"), c.get("output")] for c in calls])
        answer = answer2
    return {"answer": answer, "citations": ctx.get("citations", []), "tool_calls": calls, "routes": ctx.get("routes", []),
            "verification": {"passed": check["passed"] and not _missing_citations(answer, ctx),
                             "unverified": check["unverified"], "verified_count": len(check["verified"])},
            "mode": "live", "provider": prov, "model": model_name, "constraints": _constraints_from_calls(calls)}


def _missing_citations(answer: str, ctx: dict) -> list[str]:
    have = {c["n"] for c in ctx.get("citations", [])}
    return [f"[{n}]" for n in sorted({int(x) for x in re.findall(r"\[(\d+)\]", answer)}) if n not in have]


def _constraints_from_calls(calls: list[dict]) -> dict | None:
    for c in calls:
        if c["name"] in ("plan_route", "replan"):
            return {"tool": c["name"], **c["input"]}
    return None


# --- offline mode ----------------------------------------------------------------------------

TARGET_WORDS = {
    "rochette": ["rochette", "maaz", "máaz", "basalt", "igneous", "montdenier"],
    "seitah": ["seitah", "séítah", "olivine", "brac", "cumulate"],
    "skinner_ridge": ["skinner"],
    "wildcat_ridge": ["wildcat", "organic", "sulfate", "mudstone", "hydrated", "clay", "delta"],
    "three_forks": ["three forks", "depot", "cache"],
}


def parse_constraints(text: str) -> dict:
    """Deterministic constraint parser (offline mode and UI preview)."""
    t = text.lower()
    targets = [tid for tid, words in TARGET_WORDS.items() if any(w in t for w in words)]
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|\s)?\s*(?:hours?|hrs?|h)\b", t)
    hazard = "dust_storm" if "dust" in t else "suit_fault" if ("leak" in t or "suit fault" in t) else None
    objective = "safest" if "safe" in t else "fastest" if ("fast" in t or "quick" in t) else "all"
    return {"targets": targets or ["wildcat_ridge"], "max_duration_h": float(hours.group(1)) if hours else None,
            "hazard": hazard, "objective": objective, "inferred_target": not targets,
            "estimate_request": bool(re.search(r"\b(estimate|roughly|guess|ballpark)\b", t))}


def offline_answer(text: str) -> dict:
    c = parse_constraints(text)
    ctx: dict = {}
    calls = []
    args = {"targets": c["targets"], "objective": c["objective"]}
    if c["max_duration_h"]:
        args["max_duration_h"] = c["max_duration_h"]
    if c["hazard"]:
        args["hazard"] = c["hazard"]
    plan = tools.run_tool("plan_route", args, ctx)
    calls.append({"name": "plan_route", "input": args, "output": plan})
    q = "EVA metabolic rate oxygen consumption PLSS" if not c["hazard"] else "EVA contingency abort return to lunar module"
    docs = tools.run_tool("search_docs", {"query": q, "k": 2}, ctx)
    calls.append({"name": "search_docs", "input": {"query": q, "k": 2}, "output": docs})
    lines = [f"Constraints: targets {', '.join(c['targets'])}"
             + (f", EVA limit {args['max_duration_h']} h" if c["max_duration_h"] else "")
             + (f", hazard {c['hazard']}" if c["hazard"] else "") + "."]
    if c["estimate_request"]:
        lines.append("I don't estimate consumables; these figures come from the planner.")
    for r in plan["routes"]:
        status = "feasible" if r["feasible"] else "NOT feasible"
        line = (f"{r['label']}: {r['distance_km']} km, {r['duration_h']} hours, O2 used {r['o2_kg']:.3f} kg "
                f"({r['o2_remaining_kg']:.3f} kg left), battery used {r['batt_wh']:.0f} Wh, {status}.")
        if r.get("point_of_no_return"):
            p = r["point_of_no_return"]
            line += f" Point of no return at T+{p['t_min']} minutes."
        lines.append(line)
    first = plan["routes"][0] if plan["routes"] else {}
    if first.get("comms"):
        cm, rad = first["comms"], first["radiation"]
        lines.append(f"On {first['label']}: radio line of sight to the habitat on {cm['line_of_sight_pct']}% of the route, "
                     f"longest dead zone {cm['longest_dead_zone_min']} minutes; worst-case time to shelter "
                     f"{rad['max_time_to_shelter_min']} minutes against a {rad['sep_warning_min']} minutes solar particle rule"
                     f" ({'OK' if rad['sep_shelter_ok'] else 'NOT met'}).")
    # Quote one prose sentence (no figures) from the best passage: document numbers out of context are not shown.
    for p in docs["passages"]:
        sents = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", p["text"]))
        good = [s for s in sents if len(s.split()) >= 8 and not re.search(r"\d", s) and len(s) <= 260]
        if good:
            lines.append(f"Relevant guidance [{p['n']}]: \"{good[0]}\" ({p['title']}, p. {p['page']})")
            break
    answer = "\n".join(lines)
    check = verifier.check(answer, [[x["input"], x["output"]] for x in calls])
    return {"answer": answer, "citations": ctx.get("citations", []), "tool_calls": calls, "routes": ctx.get("routes", []),
            "verification": {"passed": check["passed"], "unverified": check["unverified"], "verified_count": len(check["verified"])},
            "mode": "offline", "model": None, "constraints": c}


if __name__ == "__main__":
    import sys

    print(json.dumps(ask([{"role": "user", "content": " ".join(sys.argv[1:]) or "Plan a 4 hour EVA to hydrated minerals"}]),
                     indent=1, default=str)[:4000])
