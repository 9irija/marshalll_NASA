"""Marswalk Mission Planner API. Run: uvicorn api.main:app --reload"""
from __future__ import annotations

import json
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from api import service
from api.routers import assistant, planning
from pipeline.geo import PROCESSED, ROOT, load_yaml


def _warm():
    """Compile numba kernels and build the default cost-to-home field off the request path."""
    try:
        from planner import fields, graph
        from planner.cost import CostParams
        from planner.envelope import default_home_field
        from planner.site import get_site

        default_home_field()
        site, p = get_site(), CostParams.from_config()
        home = (site.habitat["row"], site.habitat["col"])
        for obj in (graph.ENERGY, graph.SAFEST):
            for rev in (False, True):
                fields.get(site, p, obj, home, rev)
        from planner import science
        from planner.routes import Stop

        science.cost_matrices(site, p, [Stop(*home, "habitat", "habitat")]
                              + [Stop(h["row"], h["col"], h["id"], "hotspot") for h in site.hotspots])
        print("warm-up done: habitat fields and science matrices cached")
    except Exception as e:  # pragma: no cover - missing data in CI
        print(f"warm-up skipped: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("MARSWALK_SKIP_WARM") != "1":
        threading.Thread(target=_warm, daemon=True).start()
    yield


app = FastAPI(title="Marswalk Mission Planner", version="0.1.0", lifespan=lifespan,
              description="Can I get there, do the science, and get home alive? Jezero Crater EVA planner.")
origins = [o for o in os.getenv("WEB_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_origin_regex=os.getenv("WEB_ORIGIN_REGEX", r"https://.*\.vercel\.app"),
                   allow_methods=["*"], allow_headers=["*"])
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount("/static/web", StaticFiles(directory=PROCESSED / "web"), name="web")
app.include_router(planning.router)
app.include_router(assistant.router)


@app.get("/health")
def health():
    return {"ok": True, "demo_mode": service.DEMO_MODE, "assumptions_version": service.assumptions_version()}


@app.get("/assumptions", summary="Every model parameter with its source note")
def assumptions():
    return load_yaml("model.yaml")


@app.get("/manifest", summary="Provenance for every layer")
def manifest():
    return json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))


@app.get("/site", summary="AOI, habitat and DTM footprint")
def site():
    return json.loads((PROCESSED / "aoi_resolved.json").read_text(encoding="utf-8"))
