"""Flight Controller evals (evals/assistant_prompts.yaml).

  python -m evals.run_evals            live model if ANTHROPIC_API_KEY is set, else offline mode
  python -m evals.run_evals --offline  force the deterministic offline agent

Live runs call the Claude API once or more per prompt (cost: roughly a few cents per run with
the default model). Exit code 1 if any case fails.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

import yaml

os.environ.setdefault("MARSWALK_SKIP_WARM", "1")

from flight_controller import agent, verifier  # noqa: E402
from pipeline.geo import ROOT  # noqa: E402

OFFLINE_SKIP = {"cited_rule", "cited_geology", "conditions", "layer_value", "estimate_bait_kg"}  # need a language model


def run_case(case: dict, offline: bool) -> tuple[bool, list[str], dict]:
    t0 = time.perf_counter()
    r = agent.offline_answer(case["text"]) if offline else agent.ask([{"role": "user", "content": case["text"]}])
    problems = []
    calls = r["tool_calls"]
    names = [c["name"] for c in calls]
    # 1. every safety-critical number traceable (re-check independently of the agent)
    chk = verifier.check(r["answer"], [[c.get("input"), c.get("output")] for c in calls])
    if not chk["passed"]:
        problems.append("untraceable numbers: " + ", ".join(u["text"] for u in chk["unverified"]))
    # 2. citations map to retrieved passages
    have = {c["n"] for c in r["citations"]}
    cited = {int(n) for n in re.findall(r"\[(\d+)\]", r["answer"])}
    if cited - have:
        problems.append(f"invented citations {sorted(cited - have)}")
    if case.get("require_citation") and not (cited & have):
        problems.append("missing citation")
    # 3. behaviour
    for t in case.get("expect_tools", []):
        if t not in names:
            problems.append(f"tool {t} not called (called {names})")
    plans = [c for c in calls if c["name"] == "plan_route" and "output" in c]
    for tid in case.get("expect_targets", []):
        if not any(tid in c["input"].get("targets", []) for c in plans):
            problems.append(f"target {tid} not planned")
    if "expect_feasible" in case and plans:
        feas = {rt["feasible"] for c in plans for rt in c["output"]["routes"]}
        if feas != {case["expect_feasible"]}:
            problems.append(f"feasibility {feas}, expected {case['expect_feasible']}")
    if case.get("must_mention") and not any(m.lower() in r["answer"].lower() for m in case["must_mention"]):
        problems.append(f"answer mentions none of {case['must_mention']}")
    return not problems, problems, {"answer": r["answer"], "tools": names, "seconds": round(time.perf_counter() - t0, 1),
                                    "mode": r["mode"]}


def main() -> int:
    offline = "--offline" in sys.argv or agent._client() is None
    cases = yaml.safe_load((ROOT / "evals" / "assistant_prompts.yaml").read_text(encoding="utf-8"))["prompts"]
    results, failed = [], 0
    print(f"Flight Controller evals ({'OFFLINE deterministic agent' if offline else 'live: ' + agent.MODEL})")
    for c in cases:
        if offline and c["id"] in OFFLINE_SKIP:
            print(f"  SKIP {c['id']} (needs a language model)")
            results.append({"id": c["id"], "skipped": True})
            continue
        ok, problems, info = run_case(c, offline)
        failed += not ok
        print(f"  {'PASS' if ok else 'FAIL'} {c['id']} ({info['seconds']} s, tools {info['tools']})")
        for p in problems:
            print(f"       - {p}")
        results.append({"id": c["id"], "passed": ok, "problems": problems, **info})
    out = ROOT / "evals" / "last_run.json"
    out.write_text(json.dumps({"offline": offline, "results": results}, indent=1), encoding="utf-8")
    print(f"\n{len([r for r in results if r.get('passed')])} passed, {failed} failed, "
          f"{len([r for r in results if r.get('skipped')])} skipped. Details: {out.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
