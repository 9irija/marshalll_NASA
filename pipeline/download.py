"""Download every raw NASA / USGS product the pipeline needs (idempotent, ~1.05 GB total).

All URLs were discovered from the archive indexes (HiRISE PDS, PDS Geosciences ODE
REST API, Mars 2020 MMGIS, USGS Publications Warehouse); none are guessed. Run: python -m pipeline.download
"""
from __future__ import annotations

import sys
import urllib.request
import zipfile
from pathlib import Path

from pipeline.geo import RAW

HIRISE = "https://hirise-pds.lpl.arizona.edu/PDS/DTM/PSP/ORB_002300_002399/PSP_002387_1985_PSP_003798_1985"
CRISM = "https://pds-geosciences.wustl.edu/mro/mro-m-crism-5-rdr-mptargeted-v1/mrocr_4001/mtrdr"
MMGIS = "https://mars.nasa.gov/mmgis-maps/M20/Layers/json"

FILES: dict[str, list[str]] = {
    "hirise": [
        f"{HIRISE}/DTEEC_002387_1985_003798_1985_A01.IMG",
        f"{HIRISE}/PSP_002387_1985_RED_C_01_ORTHO.JP2",
        f"{HIRISE}/PSP_002387_1985_RED_C_01_ORTHO.LBL",
    ],
    "crism": [
        f"{CRISM}/2007/2007_057/frt000047a3/frt000047a3_07_su166j_mtr3.{ext}" for ext in ("img", "hdr", "lbl")
    ]
    + [f"{CRISM}/2007/2007_139/frt00005c5e/frt00005c5e_07_su166j_mtr3.{ext}" for ext in ("img", "hdr", "lbl")],
    "m20": [f"{MMGIS}/M20_traverse.json", f"{MMGIS}/M20_waypoints.json"],
    "meda": ["https://mars.nasa.gov/rss/api/?feed=weather&category=mars2020&feedtype=json"],
    # USGS SIM 3464 geologic map of Jezero (Sun & Stack 2020) with THEMIS day/night IR controlled mosaics, 349 MB
    "usgs": ["https://pubs.usgs.gov/sim/3464/sim3464_database.zip"],
}
NAMES = {"https://mars.nasa.gov/rss/api/?feed=weather&category=mars2020&feedtype=json": "mars2020_weather_feed.json"}


def fetch(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  have {dest.relative_to(RAW)}")
        return
    print(f"  get  {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(dest)


def main() -> int:
    for group, urls in FILES.items():
        d = RAW / group
        d.mkdir(parents=True, exist_ok=True)
        for url in urls:
            fetch(url, d / NAMES.get(url, url.rsplit("/", 1)[-1]))
    z = RAW / "usgs" / "sim3464_database.zip"
    if z.exists() and not (RAW / "usgs" / "sim3464_JezeroNili_FINAL").exists():
        with zipfile.ZipFile(z) as f:
            f.extractall(RAW / "usgs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
