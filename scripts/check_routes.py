"""Run the planner on tests/route_cases.yaml and report cost, length, slope and deviation.

Run: python -m scripts.check_routes      (exit code 1 if any expectation fails)
"""
from __future__ import annotations

import os
import sys
import time

import yaml

os.environ.setdefault("MARSWALK_SKIP_WARM", "1")

from api import service  # noqa: E402
from api.schemas import RouteRequest  # noqa: E402
from pipeline.geo import ROOT  # noqa: E402


def check_case(c: dict) -> tuple[list[str], list[str]]:
    t0 = time.perf_counter()
    res = service.plan(RouteRequest(targets=c["targets"], objective="all", hazard=c.get("hazard"), params=c.get("params")))
    ms = (time.perf_counter() - t0) * 1000
    lines, fails = [], []
    e = c.get("expect", {})
    safest = next(r for r in res["routes"] if r["objective"] == "safest")
    for r in res["routes"]:
        t = r["totals"]
        pnr = r.get("point_of_no_return")
        lines.append(f"  {c['id']:18s} {r['objective']:8s} {t['distance_m'] / 1000:6.2f} km {t['duration_s'] / 3600:5.2f} h "
                     f"O2 {t['o2_kg']:.3f} kg batt {t['batt_wh']:5.0f} Wh slope<={t['max_slope_deg']:4.1f} "
                     f"{'OK ' if t['feasible'] else 'NO '}{'PNR T+%.0f min' % (pnr['t_s'] / 60) if pnr else ''}")
        if "max_slope_deg_le" in e and t["max_slope_deg"] > e["max_slope_deg_le"] + 1e-6:
            fails.append(f"{c['id']}/{r['objective']}: max slope {t['max_slope_deg']:.1f} > {e['max_slope_deg_le']}")
    t = safest["totals"]
    if "feasible" in e and t["feasible"] != e["feasible"]:
        fails.append(f"{c['id']}: feasible={t['feasible']}, expected {e['feasible']}")
    if "distance_km_between" in e:
        lo, hi = e["distance_km_between"]
        if not lo <= t["distance_m"] / 1000 <= hi:
            fails.append(f"{c['id']}: safest distance {t['distance_m'] / 1000:.2f} km outside [{lo}, {hi}]")
    if e.get("pnr") and not safest.get("point_of_no_return"):
        fails.append(f"{c['id']}: expected a point of no return")
    lines.append(f"  {'':18s} computed in {ms:.0f} ms")
    return lines, fails


def main() -> int:
    spec = yaml.safe_load((ROOT / "tests" / "route_cases.yaml").read_text(encoding="utf-8"))
    all_fails = []
    print("Route cases")
    for c in spec["cases"]:
        lines, fails = check_case(c)
        print("\n".join(lines))
        all_fails += fails
    print("Perseverance validation")
    for v in spec.get("validation", []):
        r = service.validate_route(v["sol_from"], v["sol_to"], None, None)
        print(f"  sols {v['sol_from']}->{v['sol_to']}: rover {r['actual']['length_m'] / 1000:.2f} km, ours {r['planned']['length_m'] / 1000:.2f} km, "
              f"mean deviation {r['mean_deviation_m']} m, Frechet {r['frechet_m']} m")
        e = v["expect"]
        if r["mean_deviation_m"] > e["mean_deviation_m_le"] or r["frechet_m"] > e["frechet_m_le"]:
            all_fails.append(f"validation {v}: deviation too large")
    print("\n" + ("ALL CASES PASS" if not all_fails else "FAILURES:\n  " + "\n  ".join(all_fails)))
    return 1 if all_fails else 0


if __name__ == "__main__":
    sys.exit(main())
