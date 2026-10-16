from __future__ import annotations

from fastapi import APIRouter, HTTPException

from api.schemas import AssistantRequest

router = APIRouter()


@router.post("/assistant", summary="Flight Controller: natural-language EVA planning with verified numbers")
def post_assistant(req: AssistantRequest):
    from flight_controller import agent

    if not req.messages or req.messages[-1].role != "user":
        raise HTTPException(422, "last message must be from the user")
    if not req.confirm_constraints:
        return {"constraints": agent.parse_constraints(req.messages[-1].content), "mode": "preview"}
    return agent.ask([m.model_dump() for m in req.messages])
