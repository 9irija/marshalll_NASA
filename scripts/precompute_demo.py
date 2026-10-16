"""Precompute the demo responses (DEMO_MODE and the static web fallback).

Run: python -m scripts.precompute_demo
Writes data/processed/demo/: named files for the web app (static fallback) and
request-hash files for the API's DEMO_MODE.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

os.environ["MARSWALK_SKIP_WARM"] = "1"

from api import service  # noqa: E402
from api.demo import key  # noqa: E402
from api.schemas import EnvelopeRequest, RouteRequest, ValidateRequest  # noqa: E402
from pipeline.geo import PROCESSED, ROOT, load_yaml  # noqa: E402

OUT = PROCESSED / "demo"
DEMO_TARGETS = ["wildcat_ridge", "seitah", "rochette", "skinner_ridge", "three_forks"]


def dump(name: str, obj) -> None:
    (OUT / name).write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    dump("layers.json", service.layers())
    dump("targets.json", service.targets())
    dump("site.json", json.loads((PROCESSED / "aoi_resolved.json").read_text()))
    dump("assumptions.json", load_yaml("model.yaml"))
    dump("manifest.json", json.loads((ROOT / "data" / "manifest.json").read_text()))
    dump("conditions.json", service.conditions(None))
    for tid in DEMO_TARGETS:
        req = RouteRequest(targets=[tid], objective="all", params={"max_duration_s": 4 * 3600})
        res = service.plan(req)
        for r in res["routes"]:
            env = service.envelope_for(EnvelopeRequest(route_id=r["id"], timestep_s=300, polygons=False))
            src = PROCESSED / "web" / "runtime" / f"deadline_{r['id']}.png"
            shutil.copy(src, OUT / f"deadline_{tid}_{r['objective']}.png")
            env["deadline_field"]["url"] = f"demo/deadline_{tid}_{r['objective']}.png"
            dump(f"envelope_{tid}_{r['objective']}.json", env)
        dump(f"route_{tid}.json", res)
        dump(f"{key('route', req)}.json", res)
        print(f"  {tid}: " + ", ".join(f"{r['objective']} {r['totals']['distance_m']:.0f} m" for r in res["routes"]))
    v = service.validate_route(None, None, None, None)
    dump("validate.json", v)
    dump(f"{key('validate', ValidateRequest())}.json", v)
    print(f"  validate: mean dev {v['mean_deviation_m']} m, frechet {v['frechet_m']} m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
