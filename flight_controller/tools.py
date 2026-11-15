"""Tools the Flight Controller may call. Every safety-critical number in an answer
must come from the result of one of these, in the same turn (enforced by verifier.py)."""
from __future__ import annotations

import json
from typing import Any

from api import service
from api.schemas import EnvelopeRequest, LatLon, ReplanRequest, RouteRequest, SimilarRequest
from flight_controller import retrieval

_TARGET_IDS = "rochette, seitah, skinner_ridge, wildcat_ridge, three_forks"
_POINT = {"type": "object", "properties": {"lat": {"type": "number"}, "lon": {"type": "number"}},
          "required": ["lat", "lon"], "additionalProperties": False}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "plan_route",
        "description": "Plan EVA routes from the habitat on the HiRISE terrain of Jezero crater. Returns safest, fastest "
                       "and most-science routes (or one objective) with distance, duration, O2 and battery use, reserves, "
                       "feasibility and the point of no return. Call this before stating any route number. Target ids: "
                       + _TARGET_IDS + ". Use max_duration_h for EVA time limits. mode='rover' plans a riding EVA whose "
                       "return envelope still assumes walking home (Apollo walkback rule). Each route also reports radio "
                       "dead zones, cosmic-ray dose, worst-case time to shelter for a solar particle event and geology crossed.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {
            "targets": {"type": "array", "items": {"type": "string"}, "description": "Target ids, in visiting order"},
            "objective": {"type": "string", "enum": ["all", "safest", "fastest", "science"]},
            "max_duration_h": {"type": "number", "description": "EVA time limit in hours"},
            "hazard": {"type": "string", "enum": ["dust_storm", "suit_fault"]},
            "mode": {"type": "string", "enum": ["walk", "rover"]},
            "round_trip": {"type": "boolean"}}, "required": ["targets"]},
    },
    {
        "name": "get_envelope",
        "description": "Return envelope for a planned route: area still safe (can get home with reserve) every N "
                       "minutes, the point of no return and the tightest point. Needs a route_id from plan_route.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {
            "route_id": {"type": "string"}, "timestep_min": {"type": "number"}}, "required": ["route_id"]},
    },
    {
        "name": "replan",
        "description": "Replan from the astronaut's current position given remaining O2 (kg) and battery (Wh), "
                       "optionally under a hazard. Always returns an abort route home and, if targets are given, a "
                       "continue option with a recommendation.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {
            "lat": {"type": "number"}, "lon": {"type": "number"}, "t_s": {"type": "number"},
            "o2_kg": {"type": "number"}, "batt_wh": {"type": "number"},
            "hazard": {"type": "string", "enum": ["dust_storm", "suit_fault", "solar_particle_event"]},
            "targets": {"type": "array", "items": {"type": "string"}}},
            "required": ["lat", "lon", "t_s", "o2_kg", "batt_wh"]},
    },
    {
        "name": "get_conditions",
        "description": "Weather at Jezero from the Mars 2020 MEDA feed for a sol (nearest available): temperature, "
                       "pressure, season, sunrise and sunset.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {"sol": {"type": "integer"}}},
    },
    {
        "name": "get_layer_value",
        "description": "Value of a map layer at a point: elevation (m), slope (deg), hazard (0-1), science (0-1), "
                       "olivine, fe_mg_smectite, carbonate, hydration (0-1, CRISM relative index).",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {
            "lat": {"type": "number"}, "lon": {"type": "number"},
            "layer": {"type": "string", "enum": ["elevation", "slope", "hazard", "science", "olivine", "fe_mg_smectite",
                                                 "carbonate", "hydration"]}},
            "required": ["lat", "lon", "layer"]},
    },
    {
        "name": "get_space_weather",
        "description": "Space weather from NASA DONKI: CMEs modelled (WSA-ENLIL) to reach Mars, recent SEP events and "
                       "M/X flares, and the cosmic-ray dose baseline measured on the Mars surface by MSL RAD.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    {
        "name": "find_similar_ground",
        "description": "Machine-learning search for ground similar to a point (CRISM minerals, THEMIS thermal, HiRISE "
                       "brightness, slope, roughness, relief), screened for reachability. Proposes candidate sites only: "
                       "call plan_route to a candidate before stating any O2, battery or time for it.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {
            "lat": {"type": "number"}, "lon": {"type": "number"}, "k": {"type": "integer"},
            "max_duration_h": {"type": "number"}}, "required": ["lat", "lon"]},
    },
    {
        "name": "search_docs",
        "description": "Search the curated corpus of public NASA documents (EVA consumables, walkback and abort "
                       "practice, Apollo surface operations, human landing sites, Jezero geology, dataset docs). "
                       "Returns numbered passages; cite them as [n].",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {
            "query": {"type": "string"}, "k": {"type": "integer"}}, "required": ["query"]},
    },
]

ROUTE_KEYS = ("distance_m", "duration_s", "o2_kg", "batt_wh", "o2_remaining_kg", "batt_remaining_wh", "o2_reserve_kg",
              "batt_reserve_wh", "max_slope_deg", "mean_hazard", "stops", "feasible", "within_duration")


def _summarise_route(r: dict) -> dict:
    t = r["totals"]
    out = {"route_id": r["id"], "objective": r["objective"], "label": r["label"], **{k: t[k] for k in ROUTE_KEYS if k in t}}
    out["duration_h"] = round(t["duration_s"] / 3600, 2)
    out["distance_km"] = round(t["distance_m"] / 1000, 2)
    out["stops_visited"] = [s["name"] for s in r["stops"] if s["kind"] != "habitat"]
    out["mode"] = r.get("mode", "walk")
    c = r.get("context") or {}
    if c:
        out["comms"] = {"line_of_sight_pct": round(100 * c["comms"]["line_of_sight_fraction"], 1),
                        "dead_zones": len(c["comms"]["dead_zones"]),
                        "time_out_of_contact_min": round(c["comms"]["time_out_of_contact_s"] / 60, 1),
                        "longest_dead_zone_min": round(c["comms"]["longest_dead_zone_s"] / 60, 1)}
        rad = c["radiation"]
        out["radiation"] = {"gcr_dose_msv": rad["gcr_dose_msv"], "max_time_to_shelter_min": round(rad["max_time_to_shelter_s"] / 60, 1),
                            "sep_warning_min": round(rad["sep_warning_s"] / 60, 1), "sep_shelter_ok": rad["sep_shelter_ok"]}
        out["geology"] = [{"unit": g["name"], "distance_m": g["distance_m"]} for g in c["geology"]]
    for k in ("point_of_no_return", "tightest_point"):
        if r.get(k):
            p = r[k]
            out[k] = {"lat": round(p["lat"], 5), "lon": round(p["lon"], 5), "t_min": round(p["t_s"] / 60, 1),
                      **({"slack_min": round(p["slack_s"] / 60, 1)} if "slack_s" in p else {})}
    return out


def run_tool(name: str, args: dict, ctx: dict) -> dict:
    """Execute a tool; ctx collects citations and raw results for the verifier and the UI."""
    if name == "plan_route":
        params = {"max_duration_s": args["max_duration_h"] * 3600} if args.get("max_duration_h") else None
        res = service.plan(RouteRequest(targets=args["targets"], objective=args.get("objective", "all"),
                                        hazard=args.get("hazard"), round_trip=args.get("round_trip", True), params=params,
                                        mode=args.get("mode", "walk")))
        ctx.setdefault("routes", []).extend(res["routes"])
        return {"assumptions_version": res["assumptions_version"], "routes": [_summarise_route(r) for r in res["routes"]]}
    if name == "get_envelope":
        res = service.envelope_for(EnvelopeRequest(route_id=args["route_id"], timestep_s=60 * args.get("timestep_min", 30)))
        return {"route_id": res["route_id"], "point_of_no_return": res["point_of_no_return"], "tightest_point": res["tightest_point"],
                "frames": [{"t_min": round(f["t_s"] / 60, 1), "safe_area_km2": f["area_km2"]} for f in res["frames"]]}
    if name == "replan":
        res = service.replan(ReplanRequest(current_position=LatLon(lat=args["lat"], lon=args["lon"]), t_s=args["t_s"],
                                           remaining={"o2_kg": args["o2_kg"], "batt_wh": args["batt_wh"]},
                                           hazard=args.get("hazard"), targets=args.get("targets", [])))
        ctx.setdefault("routes", []).extend(res["routes"])
        return {"recommendation": res["recommendation"], "hazard": res["hazard"], "routes": [_summarise_route(r) for r in res["routes"]],
                **({"shelter": {"time_to_habitat_min": round(res["shelter"]["time_to_habitat_s"] / 60, 1),
                                "warning_min": round(res["shelter"]["warning_s"] / 60, 1),
                                "within_warning": res["shelter"]["within_warning"]}} if res.get("shelter") else {})}
    if name == "get_space_weather":
        w = service.space_weather()
        return {k: w[k] for k in ("status", "window", "upcoming_mars_impacts", "mars_cme_impacts", "sep_events", "flares_m_or_x",
                                  "baseline", "rule", "limits")}
    if name == "find_similar_ground":
        params = {"max_duration_s": args["max_duration_h"] * 3600} if args.get("max_duration_h") else None
        s = service.similar(SimilarRequest(lat=args["lat"], lon=args["lon"], k=int(args.get("k", 5)), params=params))
        return {"query": s["query"], "note": s["note"],
                "candidates": [{**{k: c[k] for k in ("lat", "lon", "similarity", "geology", "science_value")},
                                "screen_round_trip_min": round(c["est_round_trip_s"] / 60)} for c in s["candidates"]],
                "validation": {"nmi_vs_usgs": s["model"]["validation"]["nmi_vs_usgs"]}}
    if name == "get_conditions":
        return service.conditions(args.get("sol"))
    if name == "get_layer_value":
        return service.layer_value(args["layer"], args["lat"], args["lon"])
    if name == "search_docs":
        hits = retrieval.search(args["query"], int(args.get("k", 4)))
        cites = ctx.setdefault("citations", [])
        out = []
        for h in hits:
            key = h["chunk_id"]
            idx = next((c["n"] for c in cites if c["chunk_id"] == key), None)
            if idx is None:
                idx = len(cites) + 1
                cites.append({"n": idx, "chunk_id": key, "title": h["title"], "url": h["url"], "page": h["page"]})
            out.append({"n": idx, "title": h["title"], "page": h["page"], "text": h["text"]})
        return {"passages": out}
    raise ValueError(f"unknown tool {name}")


def dumps(x: Any) -> str:
    return json.dumps(x, default=str)
