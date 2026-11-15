from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from api import service
from api.demo import demo_or
from api.schemas import ChecklistRequest, EnvelopeRequest, ReplanRequest, RouteRequest, SimilarRequest, ValidateRequest
from planner.checklist import cuff_html
from planner.site import get_site

router = APIRouter()


def _guard(fn, *a):
    try:
        return fn(*a)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'\"")) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/layers", summary="Layers with tile URLs and provenance ids")
def get_layers():
    return service.layers()


@router.get("/layers/{layer_id}/value", summary="Layer value at a point")
def get_layer_value(layer_id: str, lat: float = Query(..., ge=-90, le=90), lon: float = Query(..., ge=-180, le=180)):
    return _guard(service.layer_value, layer_id, lat, lon)


@router.get("/targets", summary="Named science targets (rover waypoints)")
def get_targets():
    return service.targets()


@router.post("/route", summary="Plan safest / fastest / most-science routes")
def post_route(req: RouteRequest):
    return demo_or("route", req, lambda: _guard(service.plan, req))


@router.post("/envelope", summary="Return envelope frames and point of no return for a route")
def post_envelope(req: EnvelopeRequest):
    return demo_or("envelope", req, lambda: _guard(service.envelope_for, req))


@router.post("/replan", summary="Replan from the current position with remaining consumables")
def post_replan(req: ReplanRequest):
    return demo_or("replan", req, lambda: _guard(service.replan, req))


@router.get("/conditions", summary="MEDA weather for a sol (nearest available)")
def get_conditions(sol: int | None = None):
    return _guard(service.conditions, sol)


@router.post("/validate", summary="Compare a planned route with Perseverance's real traverse")
def post_validate(req: ValidateRequest):
    return demo_or("validate", req, lambda: _guard(service.validate_route, req.sol_from, req.sol_to, req.start, req.end))


@router.post("/checklist", response_class=HTMLResponse, summary="Printable cuff checklist")
def post_checklist(req: ChecklistRequest):
    r = _guard(service.get_route, req.route_id)
    return HTMLResponse(cuff_html(get_site(), r))


@router.get("/checklist/{route_id}", response_class=HTMLResponse, include_in_schema=False)
def get_checklist(route_id: str):
    return post_checklist(ChecklistRequest(route_id=route_id))


@router.post("/similar", summary="ML: find reachable ground similar to a point (candidates to verify with /route)")
def post_similar(req: SimilarRequest):
    return _guard(service.similar, req)


@router.get("/ml", summary="ML model card: features, validation against the USGS geologic map")
def get_ml():
    return _guard(service.ml_model)


@router.get("/spaceweather", summary="Space weather from NASA DONKI: CMEs predicted at Mars, SEP events, flares")
def get_spaceweather():
    return service.space_weather()


@router.get("/pov", summary="Perseverance raw images at each stop (what the crew will see)")
def get_pov(stop_id: str | None = None):
    return _guard(service.pov, stop_id)


@router.get("/mapsheet/{route_id}.png", summary="Printable annotated mission map (PNG) for a planned route")
def get_mapsheet(route_id: str):
    from planner import mapsheet

    r = _guard(service.get_route, route_id)
    return Response(mapsheet.render(get_site(), r), media_type="image/png")
