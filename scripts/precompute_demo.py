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
from api.schemas import EnvelopeRequest, RouteRequest, SimilarRequest, ValidateRequest  # noqa: E402
from pipeline.geo import PROCESSED, ROOT, load_yaml  # noqa: E402
from planner import mapsheet  # noqa: E402

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
    dump("spaceweather.json", service.space_weather())
    site = service.get_site()
    for tid in DEMO_TARGETS:
        for mode in ("walk", "rover"):
            req = RouteRequest(targets=[tid], objective="all", params={"max_duration_s": 4 * 3600}, mode=mode)
            try:
                res = service.plan(req)
            except ValueError as e:
                print(f"  {tid} ({mode}): {e}")
                continue
            tag = tid if mode == "walk" else f"{tid}_rover"
            for r in res["routes"]:
                env = service.envelope_for(EnvelopeRequest(route_id=r["id"], timestep_s=300, polygons=False))
                src = PROCESSED / "web" / "runtime" / f"deadline_{r['id']}.png"
                shutil.copy(src, OUT / f"deadline_{tag}_{r['objective']}.png")
                env["deadline_field"]["url"] = f"demo/deadline_{tag}_{r['objective']}.png"
                dump(f"envelope_{tag}_{r['objective']}.json", env)
                (OUT / f"mapsheet_{tag}_{r['objective']}.png").write_bytes(mapsheet.render(site, service.get_route(r["id"])))
            dump(f"route_{tag}.json", res)
            dump(f"{key('route', req)}.json", res)
            print(f"  {tag}: " + ", ".join(f"{r['objective']} {r['totals']['distance_m']:.0f} m" for r in res["routes"]))
        t = next(x for x in site.targets if x["id"] == tid)
        sim = service.similar(SimilarRequest(lat=t["lat"], lon=t["lon"], params={"max_duration_s": 4 * 3600}))
        png = PROCESSED / "web" / sim["similarity_map"]["url"].split("/static/web/")[1]
        shutil.copy(png, OUT / f"similar_{tid}.png")
        sim["similarity_map"]["url"] = f"demo/similar_{tid}.png"
        dump(f"similar_{tid}.json", sim)
    v = service.validate_route(None, None, None, None)
    dump("validate.json", v)
    dump(f"{key('validate', ValidateRequest())}.json", v)
    print(f"  validate: mean dev {v['mean_deviation_m']} m, frechet {v['frechet_m']} m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
