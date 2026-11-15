"""Planner services shared by the HTTP API and the Flight Controller tools.

Everything numeric that reaches a user goes through these functions, so the same
code path answers the web app and the language-model agent.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from collections import OrderedDict
from dataclasses import replace

import numpy as np

from api import spaceweather
from api.schemas import EnvelopeRequest, LatLon, ReplanRequest, RouteRequest, SimilarRequest
from pipeline.geo import PROCESSED, RAW, ROOT, load_yaml
from pipeline.layers.render import write_png
from planner import awareness, envelope, ml, routes, science, validate
from planner.cost import CostParams
from planner.routes import Route, Stop
from planner.site import Site, get_site

ROUTES: OrderedDict[str, Route] = OrderedDict()
MAX_ROUTES = 64
DEMO_MODE = os.getenv("DEMO_MODE", "0").lower() in ("1", "true", "yes")
DEMO_DIR = PROCESSED / "demo"


def assumptions_version() -> str:
    return load_yaml("model.yaml")["version"]


def _remember(r: Route) -> None:
    ROUTES[r.id] = r
    while len(ROUTES) > MAX_ROUTES:
        ROUTES.popitem(last=False)


def get_route(route_id: str) -> Route:
    if route_id not in ROUTES:
        raise KeyError(f"unknown route_id {route_id!r} (routes are kept in memory; plan again)")
    return ROUTES[route_id]


def _stop(site: Site, x: LatLon | str | dict, p: CostParams, kind: str = "target") -> Stop:
    if isinstance(x, dict):
        x = LatLon(**x)
    if isinstance(x, str):
        t = next((t for t in site.targets if t["id"] == x), None)
        if t is None:
            raise ValueError(f"unknown target id {x!r}; known: {[t['id'] for t in site.targets]}")
        return Stop(t["row"], t["col"], t["name"], kind, id=t["id"])
    r, c = site.snap_passable(*site.rc(x.lat, x.lon), p.max_slope_deg)
    return Stop(r, c, f"{x.lat:.5f}N {x.lon:.5f}E", kind)


def habitat_stop(site: Site) -> Stop:
    h = site.habitat
    return Stop(h["row"], h["col"], h["name"], "habitat", id="habitat")


def plan(req: RouteRequest) -> dict:
    site = get_site()
    p = CostParams.from_config(req.params, req.hazard)
    start = habitat_stop(site) if req.start is None else _stop(site, req.start, p, "habitat")
    stops = [_stop(site, t, p) for t in req.targets]
    if req.end is not None:
        stops.append(_stop(site, req.end, p))
    if not stops:
        raise ValueError("give `end` or at least one entry in `targets`")
    end = start if req.round_trip else stops.pop()
    if not req.round_trip:
        end.kind = "target"
    objectives = ("safest", "fastest", "science") if req.objective == "all" else (req.objective,)
    t0 = time.perf_counter()
    try:
        rs = science.plan_pareto(site, p, start, stops, end, objectives, mode=req.mode)
    except ValueError as e:
        if req.mode == "rover" and "no passable route" in str(e):
            lim = routes.rover_config()["max_slope_deg"]
            raise ValueError(f"The rover cannot reach this destination within its {lim} deg slope limit. "
                             "Plan it as a walking EVA, or pick a nearby stop on gentler ground.") from e
        raise
    out = []
    for r in rs:
        _remember(r)
        out.append(routes.to_geojson(site, r))
    return {"routes": out, "assumptions_version": p.version, "hazard": req.hazard, "params": p.overrides, "mode": req.mode,
            "compute_ms": round((time.perf_counter() - t0) * 1000, 1)}


def envelope_for(req: EnvelopeRequest) -> dict:
    site = get_site()
    rid = req.route_id or (req.route or {}).get("id")
    r = get_route(rid)
    T = r.deadline
    p = r.params
    if req.reserve_margin is not None:
        p = replace(p, o2_reserve_frac=req.reserve_margin, batt_reserve_frac=req.reserve_margin)
        hf = envelope.home_field(site, p, (site.habitat["row"], site.habitat["col"]))
        T = envelope.deadline_field(hf, p, r.seg["t_s"], r.seg["o2_kg"], r.seg["batt_wh"])
    # frames run to the end of the EVA time limit, so the envelope can be watched closing on the habitat
    times = np.arange(0.0, p.max_duration_s + 0.5 * req.timestep_s, req.timestep_s)
    cell_km2 = site.grid.res_m ** 2 / 1e6
    if req.polygons:
        frames = envelope.envelope_polygons(site, T, times)
    else:
        frames = [{"t_s": float(t), "area_km2": round(float((T >= t).sum()) * cell_km2, 4)} for t in times]
    png = PROCESSED / "web" / "runtime" / f"deadline_{r.id}.png"
    png.parent.mkdir(exist_ok=True)
    write_png(png, envelope.encode_deadline_png(T[::2, ::2], p.max_duration_s))
    m = routes.to_geojson(site, r)
    return {"route_id": r.id, "frames": frames, "point_of_no_return": m.get("point_of_no_return"),
            "tightest_point": m.get("tightest_point"),
            "deadline_field": {"url": f"/static/web/runtime/{png.name}", "bounds": site.grid.bounds_deg,
                               "t_max_s": p.max_duration_s,
                               "encoding": "R = round(T/t_max*255); A=0 where never safe; row 0 = north"},
            "habitat": {"lat": site.habitat["lat"], "lon": site.habitat["lon"]},
            "assumptions_version": p.version}


def replan(req: ReplanRequest) -> dict:
    site = get_site()
    p = CostParams.from_config(req.params, req.hazard)
    here = _stop(site, req.current_position, p, "start")
    home = habitat_stop(site)
    o2, batt = req.remaining.o2_kg, req.remaining.batt_wh
    out = []
    abort = _offset(routes.build_route(site, p, "safest", [here, home], o2, batt), req.t_s, site, p, o2, batt)
    abort.objective = "abort"
    out.append(abort)
    if req.targets and req.hazard != "solar_particle_event":    # SEP: shelter now, no continue option
        stops = [_stop(site, t, p) for t in req.targets]
        try:
            for r in science.plan_pareto(site, p, here, stops, home, (req.objective,), o2, batt):
                out.append(_offset(r, req.t_s, site, p, o2, batt))
        except ValueError:
            pass
    res = []
    for r in out:
        _remember(r)
        g = routes.to_geojson(site, r)
        if r.objective == "abort":
            g["label"] = "Abort: return to habitat"
        res.append(g)
    rec = "abort" if (len(out) == 1 or not out[1].totals["feasible"]) else req.objective
    out_ = {"routes": res, "assumptions_version": p.version, "hazard": req.hazard, "recommendation": rec}
    if req.hazard == "solar_particle_event":
        warn = load_yaml("model.yaml")["radiation"]["sep_shelter_warning_min"]["value"] * 60
        t_home = out[0].totals["duration_s"] - req.t_s
        out_["recommendation"] = "shelter"
        out_["shelter"] = {"time_to_habitat_s": round(t_home, 1), "warning_s": warn, "within_warning": bool(t_home <= warn)}
    return out_


def _offset(r: Route, t0: float, site: Site, p: CostParams, o2: float, batt: float) -> Route:
    """Shift a replanned route onto the EVA clock (t = t0 at the current position)."""
    if t0:
        r.seg["t_s"] = r.seg["t_s"] + t0
        prev_o2, prev_b = p.initial_o2_kg - o2, p.battery_wh - batt
        r.seg["o2_kg"] = r.seg["o2_kg"] + prev_o2
        r.seg["batt_wh"] = r.seg["batt_wh"] + prev_b
        r = routes.finish_route(site, p, r.objective, r.rows, r.cols, r.stops, r.stop_index, r.seg, None, None,
                                time.perf_counter())
    return r


# --- conditions -----------------------------------------------------------------------------------

MEDA_URL = "https://mars.nasa.gov/rss/api/?feed=weather&category=mars2020&feedtype=json"


def _meda_feed() -> dict:
    cache = RAW / "meda" / "mars2020_weather_feed.json"
    try:
        if not DEMO_MODE and (not cache.exists() or time.time() - cache.stat().st_mtime > 6 * 3600):
            with urllib.request.urlopen(MEDA_URL, timeout=8) as r:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_bytes(r.read())
    except Exception:
        pass
    return json.loads(cache.read_text(encoding="utf-8"))


def conditions(sol: int | None = None) -> dict:
    sols = _meda_feed()["sols"]
    valid = [s for s in sols if isinstance(s.get("max_temp"), (int, float))]
    pool = valid or sols
    pick = pool[-1] if sol is None else min(pool, key=lambda s: abs(int(s["sol"]) - sol))
    num = lambda v: v if isinstance(v, (int, float)) else None  # noqa: E731
    return {
        "sol": int(pick["sol"]), "requested_sol": sol, "terrestrial_date": pick["terrestrial_date"],
        "temp_c": {"min": num(pick["min_temp"]), "max": num(pick["max_temp"])},
        "pressure_pa": num(pick["pressure"]), "dust_opacity": None,
        "ls_deg": float(pick["ls"]), "season": pick["season"], "sunrise": pick["sunrise"], "sunset": pick["sunset"],
        "available_sols": [int(s["sol"]) for s in sols],
        "source": {"mission": "Mars 2020", "instrument": "MEDA", "url": MEDA_URL,
                   "note": "Public feed publishes the latest 7 sols; dust opacity is not in the feed."},
    }


def validate_route(sol_from: int | None, sol_to: int | None, start: LatLon | None, end: LatLon | None) -> dict:
    site = get_site()
    if start and end:
        wps = validate._waypoints()

        def nearest_sol(pt):
            return min(wps, key=lambda w: (w["lat"] - pt.lat) ** 2 + (w["lon"] - pt.lon) ** 2)["sol"]

        sol_from, sol_to = sorted((nearest_sol(start), nearest_sol(end)))
    sol_from = sol_from or validate.DEFAULT_SOLS[0]
    sol_to = sol_to or validate.DEFAULT_SOLS[1]
    return validate.compare(site, sol_from, sol_to)


def layers() -> list[dict]:
    meta = json.loads((PROCESSED / "web" / "layers.json").read_text())
    manifest = {m["id"]: m for m in json.loads((ROOT / "data" / "manifest.json").read_text())["layers"]}
    units = {"slope": "deg", "hazard": "0-1", "science": "0-1", "geology": "unit", "thermal_night": "DN", "comms": "0/1",
             "ml_units": "class"}
    names = {"slope": "Slope", "hazard": "Rock hazard (proxy)", "science": "Science value", "olivine": "Olivine (CRISM)",
             "fe_mg_smectite": "Fe/Mg smectite (CRISM)", "carbonate": "Carbonate (CRISM)", "hydration": "Hydration (CRISM)",
             "ortho": "HiRISE orthoimage (local)", "geology": "Geologic units (USGS SIM 3464)",
             "thermal_night": "THEMIS night IR (thermal)", "comms": "Comms dead zones (no line of sight)",
             "ml_units": "ML terrain units"}
    out = [{"id": k, "name": names.get(k, k), "type": "overlay", "tile_url": f"/static/web/{f}",
            "bounds": meta.get("ml_bounds", meta["bounds"]) if k == "ml_units" else meta["bounds"],
            "units": units.get(k, manifest.get(k, {}).get("units", "0-1")), "provenance_id": k}
           for k, f in meta["layers"].items()]
    trek = "https://trek.nasa.gov/tiles/Mars/EQ/{label}/1.0.0//default/default028mm/{{TileMatrix}}/{{TileRow}}/{{TileCol}}.{ext}"
    for pid, ext, name in (("hirise_mosaic", "png", "HiRISE 25 cm mosaic (Trek)"), ("ctx_mosaic", "png", "CTX 6 m mosaic (Trek)"),
                           ("viking_global", "jpg", "Viking MDIM 2.1 colour (Trek)")):
        out.append({"id": pid, "name": name, "type": "wmts", "units": "DN", "provenance_id": pid,
                    "tile_url": trek.format(label=manifest[pid]["product_id"], ext=ext)})
    out.append({"id": "terrain", "name": "HiRISE DTM terrain", "type": "terrain", "units": "m", "provenance_id": "elevation",
                "tile_url": "/static/web/terrain_aoi.json"})
    out.append({"id": "traverse", "name": "Perseverance traverse", "type": "vector", "units": "", "provenance_id": "traverse",
                "tile_url": "/static/web/traverse.json"})
    return out


def similar(req: SimilarRequest) -> dict:
    if not ml.available():
        raise ValueError("ML model not built; run python -m pipeline.ml_train")
    p = CostParams.from_config(req.params)
    return ml.similar(get_site(), req.lat, req.lon, p, req.k)


def space_weather() -> dict:
    return spaceweather.space_weather(demo=DEMO_MODE)


def pov(stop_id: str | None = None) -> dict:
    d = json.loads((PROCESSED / "web" / "pov.json").read_text(encoding="utf-8"))
    if stop_id is None:
        return d
    if stop_id not in d["stops"]:
        raise KeyError(f"no images for {stop_id!r}; known: {list(d['stops'])}")
    return {**{k: v for k, v in d.items() if k != "stops"}, **d["stops"][stop_id], "id": stop_id}


def ml_model() -> dict:
    return json.loads((PROCESSED / "ml.json").read_text(encoding="utf-8"))


def targets() -> list[dict]:
    site = get_site()
    keep = ("id", "name", "lat", "lon", "science_tags", "note", "waypoint_sol", "elev_m")
    out = [{**{k: t[k] for k in keep if k in t}, "science_value": round(float(site.science[t["row"], t["col"]]), 3)}
           for t in site.targets]
    return out


def layer_value(layer: str, lat: float, lon: float) -> dict:
    site = get_site()
    if layer == "geology":
        g = awareness.geology_at(*site.rc(lat, lon))
        return {"layer": layer, "lat": lat, "lon": lon, "value": g, "units": "unit", "provenance_id": "geology"}
    if layer == "comms":
        v = int(awareness.layers()["comms"][site.rc(lat, lon)])
        return {"layer": layer, "lat": lat, "lon": lon, "value": v, "units": "line of sight 0/1", "provenance_id": "comms"}
    units = {"elevation": "m", "slope": "deg", "roughness": "0-1"}.get(layer, "0-1")
    v = site.value(layer, lat, lon)
    return {"layer": layer, "lat": lat, "lon": lon, "value": None if v is None else round(v, 4), "units": units,
            "provenance_id": layer if layer != "roughness" else "roughness"}
