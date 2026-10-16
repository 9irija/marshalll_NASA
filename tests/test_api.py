"""Integration tests for every endpoint of the API contract (real Jezero data)."""
import os

import pytest
from fastapi.testclient import TestClient

os.environ["MARSWALK_SKIP_WARM"] = "1"
from api.main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(scope="module")
def route():
    r = client.post("/route", json={"targets": ["seitah"], "objective": "all"})
    assert r.status_code == 200, r.text
    return r.json()


def test_health_and_meta():
    assert client.get("/health").json()["ok"]
    a = client.get("/assumptions").json()
    assert a["walking"]["minetti_coeffs"]["value"][0] == 280.5 and "source" in a["walking"]["suit_penalty"]
    m = client.get("/manifest").json()["layers"]
    assert {"elevation", "slope", "hazard", "science"} <= {x["id"] for x in m}
    assert all(x.get("product_id") and x.get("url") for x in m)


def test_layers_and_values():
    layers = client.get("/layers").json()
    ids = {layer["id"] for layer in layers}
    assert {"slope", "hazard", "science", "hirise_mosaic", "terrain"} <= ids
    assert all("provenance_id" in layer for layer in layers)
    v = client.get("/layers/slope/value", params={"lat": 18.445, "lon": 77.45}).json()
    assert v["units"] == "deg" and v["value"] is not None
    assert client.get("/layers/slope/value", params={"lat": 10, "lon": 10}).status_code == 422
    assert client.get("/layers/nope/value", params={"lat": 18.445, "lon": 77.45}).status_code == 404


def test_targets():
    t = client.get("/targets").json()
    assert {x["id"] for x in t} >= {"rochette", "seitah", "wildcat_ridge"}
    assert all(-180 <= x["lon"] <= 180 for x in t)


def test_route_shape(route):
    assert route["assumptions_version"]
    assert [r["objective"] for r in route["routes"]] == ["safest", "fastest", "science"]
    for r in route["routes"]:
        seg = r["segments"]
        n = len(r["geometry"]["coordinates"])
        assert all(len(seg[k]) == n for k in ("dist_m", "elev_m", "slope_deg", "t_s", "o2_kg", "batt_wh"))
        assert r["totals"]["feasible"] and r["totals"]["max_slope_deg"] <= 25.0001
    fastest = route["routes"][1]["totals"]["duration_s"]
    assert fastest <= route["routes"][0]["totals"]["duration_s"] + 1


def test_envelope(route):
    rid = route["routes"][0]["id"]
    e = client.post("/envelope", json={"route_id": rid, "timestep_s": 900}).json()
    areas = [f["area_km2"] for f in e["frames"]]
    assert len(areas) >= 2 and all(a >= b for a, b in zip(areas, areas[1:]))
    assert e["deadline_field"]["url"].endswith(".png")
    assert client.get(e["deadline_field"]["url"]).status_code == 200
    assert client.post("/envelope", json={"route_id": "missing"}).status_code == 404


def test_replan_with_dust_storm(route):
    r = route["routes"][0]
    k = len(r["segments"]["t_s"]) // 3
    lon, lat, _ = r["geometry"]["coordinates"][k]
    body = {"current_position": {"lat": lat, "lon": lon}, "t_s": r["segments"]["t_s"][k],
            "remaining": {"o2_kg": 0.6 - r["segments"]["o2_kg"][k], "batt_wh": 800 - r["segments"]["batt_wh"][k]},
            "hazard": "dust_storm", "targets": ["seitah"]}
    res = client.post("/replan", json=body).json()
    assert res["routes"][0]["objective"] == "abort" and res["recommendation"] in ("abort", "safest")
    assert res["routes"][0]["segments"]["t_s"][0] == pytest.approx(body["t_s"], abs=1)


def test_conditions():
    c = client.get("/conditions").json()
    assert c["source"]["instrument"] == "MEDA" and c["pressure_pa"] > 0
    assert client.get("/conditions", params={"sol": 1130}).json()["sol"] == 1130


def test_validate():
    v = client.post("/validate", json={}).json()
    assert v["mean_deviation_m"] >= 0 and v["frechet_m"] >= v["mean_deviation_m"]
    assert len(v["actual"]["coordinates"]) > 10


def test_checklist(route):
    html = client.post("/checklist", json={"route_id": route["routes"][0]["id"]}).text
    assert "CUFF CARD" in html and "Leave by" in html


def test_assistant_offline_and_preview():
    p = client.post("/assistant", json={"messages": [{"role": "user", "content": "4 hour EVA to olivine"}],
                                        "confirm_constraints": False}).json()
    assert p["constraints"]["targets"] == ["seitah"] and p["constraints"]["max_duration_h"] == 4
    if not os.getenv("ANTHROPIC_API_KEY"):
        a = client.post("/assistant", json={"messages": [{"role": "user", "content": "Plan a 4 hour EVA to Wildcat Ridge"}]}).json()
        assert a["mode"] == "offline" and a["verification"]["passed"] and a["citations"]
