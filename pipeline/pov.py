"""Point-of-view images: what the crew will see at each stop, from Perseverance's own cameras.

Run: python -m pipeline.pov   -> data/processed/web/pov.json

For the habitat (sol 13) and each target (its waypoint_sol, plus the next sol when the rover stayed), we list
Navcam, Mastcam-Z and Front Hazcam full frames from the public Mars 2020 raw-images feed. Images are linked, not
copied; each entry carries the camera, sol, UTC time, mast azimuth/elevation and the NASA/JPL-Caltech credit.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

from pipeline.geo import PROCESSED, load_yaml

FEED = "https://mars.nasa.gov/rss/api/?feed=raw_images&category=mars2020&feedtype=json&sol={sol}"
PICK = [("NAVCAM_LEFT", 4), ("MCZ_LEFT", 4), ("FRONT_HAZCAM_LEFT_A", 1)]
CAMERA_NAME = {"NAVCAM_LEFT": "Navcam (left)", "MCZ_LEFT": "Mastcam-Z (left)", "FRONT_HAZCAM_LEFT_A": "Front Hazcam (left)"}


def fetch(sol: int) -> list[dict]:
    with urllib.request.urlopen(FEED.format(sol=sol), timeout=30) as r:
        return json.loads(r.read().decode("utf-8")).get("images", [])


def choose(images: list[dict]) -> list[dict]:
    out = []
    for cam, n in PICK:
        cands = [i for i in images if i["camera"]["instrument"] == cam and i["sample_type"] == "Full"
                 and "(1" in (i["extended"].get("dimension") or "")]          # full-width frames, not thumbnails
        cands.sort(key=lambda i: float(i["extended"].get("mastAz") or 0))
        if len(cands) > n:                                                   # spread across azimuth
            step = len(cands) / n
            cands = [cands[int(k * step)] for k in range(n)]
        for i in cands:
            f = i["image_files"]
            out.append({"camera": CAMERA_NAME.get(cam, cam), "instrument": cam, "sol": i["sol"], "utc": i["date_taken_utc"],
                        "mast_az_deg": _f(i["extended"].get("mastAz")), "mast_el_deg": _f(i["extended"].get("mastEl")),
                        "url": f.get("large") or f.get("full_res"), "thumb": f.get("medium") or f.get("small"),
                        "full_res": f.get("full_res"), "page": i.get("link"), "title": i.get("title"), "credit": i.get("credit")})
    return out


def _f(x):
    try:
        return round(float(x), 1)
    except (TypeError, ValueError):
        return None


def main() -> int:
    aoi = load_yaml("aoi.yaml")
    stops = [{"id": "habitat", "name": aoi["habitat"]["name"], "sol": 13}] + [
        {"id": t["id"], "name": t["name"], "sol": t["waypoint_sol"]} for t in aoi["targets"]]
    out = {"source": "Mars 2020 raw images feed (mars.nasa.gov/mars2020/multimedia/raw-images)", "credit": "NASA/JPL-Caltech",
           "note": "Raw, unprocessed engineering images taken by Perseverance on the sol it stood at (or arrived at) each stop.",
           "stops": {}}
    for s in stops:
        imgs = []
        for sol in (s["sol"], s["sol"] + 1):
            try:
                imgs = choose(fetch(sol))
            except Exception as e:
                print(f"  ! {s['id']} sol {sol}: {e}")
                imgs = []
            if imgs:
                break
            time.sleep(0.5)
        out["stops"][s["id"]] = {"name": s["name"], "sol": imgs[0]["sol"] if imgs else s["sol"], "images": imgs}
        print(f"  {s['id']}: {len(imgs)} images (sol {imgs[0]['sol'] if imgs else s['sol']})")
    (PROCESSED / "web" / "pov.json").write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
