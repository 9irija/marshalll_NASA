"""Tools the Flight Controller may call. Every safety-critical number in an answer
must come from the result of one of these, in the same turn (enforced by verifier.py)."""
from __future__ import annotations

import json
from typing import Any

from api import service
from api.schemas import EnvelopeRequest, LatLon, ReplanRequest, RouteRequest
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
                       + _TARGET_IDS + ". Use max_duration_h for EVA time limits.",
        "input_schema": {"type": "object", "additionalProperties": False, "properties": {
            "targets": {"type": "array", "items": {"type": "string"}, "description": "Target ids, in visiting order"},
            "objective": {"type": "string", "enum": ["all", "safest", "fastest", "science"]},
            "max_duration_h": {"type": "number", "description": "EVA time limit in hours"},
            "hazard": {"type": "string", "enum": ["dust_storm", "suit_fault"]},
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
            "hazard": {"type": "string", "enum": ["dust_storm", "suit_fault"]},
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
                                        hazard=args.get("hazard"), round_trip=args.get("round_trip", True), params=params))
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
        return {"recommendation": res["recommendation"], "hazard": res["hazard"], "routes": [_summarise_route(r) for r in res["routes"]]}
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
