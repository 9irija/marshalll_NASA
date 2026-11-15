"""Pydantic request/response schemas for the API contract (docs/ARCHITECTURE.md)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Objective = Literal["safest", "fastest", "science"]
Hazard = Literal["dust_storm", "suit_fault", "solar_particle_event"]
Mode = Literal["walk", "rover"]


class LatLon(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180, description="East-positive, -180..180")


class Point(LatLon):
    target_id: str | None = None


class RouteRequest(BaseModel):
    start: LatLon | None = Field(None, description="Defaults to the habitat")
    end: LatLon | str | None = Field(None, description="Point or target id")
    targets: list[LatLon | str] = Field(default_factory=list, description="Ordered stops (ids or points)")
    objective: Objective | Literal["all"] = "all"
    round_trip: bool = True
    hazard: Hazard | None = None
    params: dict[str, float] | None = Field(None, description="Overrides of CostParams fields, e.g. max_duration_s")
    mode: Mode = Field("walk", description="walk, or rover (riding EVA, return envelope still costed for walking home)")


class EnvelopeRequest(BaseModel):
    route_id: str | None = None
    route: dict[str, Any] | None = Field(None, description="A route object previously returned by /route")
    timestep_s: float = Field(300, gt=0, le=3600)
    reserve_margin: float | None = Field(None, ge=0, le=0.9, description="Override reserve fraction (O2 and battery)")
    polygons: bool = True


class Remaining(BaseModel):
    o2_kg: float = Field(ge=0)
    batt_wh: float = Field(ge=0)


class ReplanRequest(BaseModel):
    current_position: LatLon
    t_s: float = Field(ge=0)
    remaining: Remaining
    hazard: Hazard | None = None
    objective: Objective = "safest"
    targets: list[LatLon | str] = Field(default_factory=list, description="Remaining stops if continuing")
    params: dict[str, float] | None = None


class ValidateRequest(BaseModel):
    start: LatLon | None = None
    end: LatLon | None = None
    sol_from: int | None = None
    sol_to: int | None = None


class ChecklistRequest(BaseModel):
    route_id: str


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AssistantRequest(BaseModel):
    messages: list[Message]
    confirm_constraints: bool = Field(True, description="If false, only parse constraints and return them for review")


class SimilarRequest(LatLon):
    k: int = Field(6, ge=1, le=20, description="Number of candidate sites")
    params: dict[str, float] | None = Field(None, description="CostParams overrides (max_duration_s screens reachability)")
