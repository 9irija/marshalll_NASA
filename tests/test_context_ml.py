"""Comms viewshed, route context, rover walkback, ML similarity, space weather and POV (real data where built)."""
import json
import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

from pipeline.context import viewshed
from pipeline.geo import MARS_RADIUS_M, PROCESSED

os.environ["MARSWALK_SKIP_WARM"] = "1"
from api.main import app  # noqa: E402

client = TestClient(app)
built = pytest.mark.skipif(not (PROCESSED / "ml.npz").exists(), reason="run pipeline.context and pipeline.ml_train")


def test_viewshed_flat_plane_all_visible_within_horizon():
    z = np.zeros((40, 60))                      # SYNTHETIC flat plane, 2 m cells: 120 m << horizon distance
    v = viewshed(z, 20, 5, 3.0, 2.0, 2.0, MARS_RADIUS_M)
    assert v.all()


def test_viewshed_wall_casts_shadow():
    z = np.zeros((40, 60))
    z[:, 20] = 10.0                             # SYNTHETIC 10 m wall between observer (col 5) and the far side
    v = viewshed(z, 20, 5, 3.0, 2.0, 2.0, MARS_RADIUS_M)
    assert v[20, 10] == 1 and v[20, 40] == 0


def test_viewshed_curvature_hides_far_ground():
    # Mars horizon for eyes at 3 m: sqrt(2 R h) ~ 4.5 km. Flat sphere-tangent ground at 8 km is below it.
    z = np.zeros((3, 2001))
    v = viewshed(z, 1, 0, 3.0, 0.0, 4.0, MARS_RADIUS_M)
    horizon = np.sqrt(2 * MARS_RADIUS_M * 3.0)
    assert v[1, int(0.8 * horizon / 4)] == 1 and v[1, 2000] == 0


@pytest.fixture(scope="module")
def walk_route():
    r = client.post("/route", json={"targets": ["wildcat_ridge"], "objective": "fastest", "params": {"max_duration_s": 14400}})
    assert r.status_code == 200, r.text
    return r.json()["routes"][0]


@built
def test_route_context(walk_route):
    c = walk_route["context"]
    assert 0 <= c["comms"]["line_of_sight_fraction"] <= 1
    assert all(z["duration_s"] >= 30 for z in c["comms"]["dead_zones"])
    rad = c["radiation"]
    dur = walk_route["totals"]["duration_s"] - walk_route["segments"]["t_s"][0]
    assert rad["gcr_dose_msv"] == pytest.approx(0.64 * dur / 86400, rel=1e-2)
    assert rad["sep_shelter_ok"] == (rad["max_time_to_shelter_s"] <= rad["sep_warning_s"])
    assert {g["symbol"] for g in c["geology"]} <= {"Njf", "Nle", "NHjf2", "Nue", "Aeb", "cr"}


@built
def test_rover_walkback(walk_route):
    r = client.post("/route", json={"targets": ["wildcat_ridge"], "objective": "fastest", "mode": "rover",
                                    "params": {"max_duration_s": 14400}})
    assert r.status_code == 200, r.text
    rv = r.json()["routes"][0]
    assert rv["mode"] == "rover" and rv["label"].startswith("Rover")
    assert rv["totals"]["duration_s"] < walk_route["totals"]["duration_s"]
    assert rv["totals"]["o2_kg"] < walk_route["totals"]["o2_kg"]
    assert rv["totals"]["max_slope_deg"] <= 20.0 + 1e-6
    # walkback: the envelope must use walking costs home, so a riding EVA cannot extend beyond walking reach
    assert rv["context"]["radiation"]["max_time_to_shelter_s"] <= walk_route["context"]["radiation"]["max_time_to_shelter_s"] + 1


@built
def test_similar_ground_returns_reachable_candidates():
    r = client.post("/similar", json={"lat": 18.45074, "lon": 77.40144, "k": 5, "params": {"max_duration_s": 14400}})
    assert r.status_code == 200, r.text
    s = r.json()
    assert 1 <= len(s["candidates"]) <= 5
    assert all(c["similarity"] > 0.9 and c["est_round_trip_s"] <= 0.85 * 14400 for c in s["candidates"])
    v = s["model"]["validation"]
    assert v["nmi_vs_usgs"] > v["nmi_shuffled"]
    assert all(lf["lift"] > 1 for lf in v["similarity_lift"])
    assert client.post("/similar", json={"lat": 10, "lon": 10}).status_code == 422


def test_sep_replan_recommends_shelter():
    r = client.post("/replan", json={"current_position": {"lat": 18.4505, "lon": 77.41}, "t_s": 3600,
                                     "remaining": {"o2_kg": 0.45, "batt_wh": 600}, "hazard": "solar_particle_event",
                                     "targets": ["wildcat_ridge"]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["recommendation"] == "shelter" and len(d["routes"]) == 1
    assert d["shelter"]["within_warning"] == (d["shelter"]["time_to_habitat_s"] <= d["shelter"]["warning_s"])


def test_spaceweather_shape(monkeypatch):
    from api import spaceweather

    sample = [{"simulationID": "S1", "modelCompletionTime": "2026-11-09T19:59Z", "link": "x",
               "cmeInputs": [{"CMEID": "C1", "cmeStartTime": "2026-11-09T18:15Z", "speed": 726.0}],
               "impactList": [{"location": "Mars", "arrivalTime": "2099-01-01T00:00Z", "isGlancingBlow": True},
                              {"location": "Earth", "arrivalTime": "2026-11-12T00:00Z"}]}]
    monkeypatch.setattr(spaceweather, "_get", lambda kind, s, e, demo: sample if kind == "WSAEnlilSimulations" else [])
    w = spaceweather.space_weather()
    assert w["status"] == "watch" and w["upcoming_mars_impacts"][0]["cme_id"] == "C1"
    assert len(w["mars_cme_impacts"]) == 1 and "model predictions" in w["limits"]


def test_pov_lists_rover_images():
    if not (PROCESSED / "web" / "pov.json").exists():
        pytest.skip("run pipeline.pov")
    d = client.get("/pov", params={"stop_id": "wildcat_ridge"}).json()
    assert d["images"] and all(i["url"].startswith("https://mars.nasa.gov/") and i["credit"] for i in d["images"])
    assert client.get("/pov", params={"stop_id": "nope"}).status_code == 404


@built
def test_new_layers_have_provenance():
    man = {m["id"]: m for m in json.loads((PROCESSED.parent / "manifest.json").read_text())["layers"]}
    for k in ("geology", "thermal_night", "comms"):
        assert man[k]["url"] and man[k]["processing"]
    assert client.get("/layers/geology/value", params={"lat": 18.445, "lon": 77.45}).json()["value"]["symbol"]
