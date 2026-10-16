"""DEMO_MODE: serve precomputed responses from data/processed/demo/ (scripts/precompute_demo.py).

Requests are keyed by a stable hash of their JSON body. In demo mode a cache miss
falls through to live computation when the planner can run; the web app has its own
static copy of the same files so it also works with the API down.
"""
from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel

from api.service import DEMO_DIR, DEMO_MODE


def key(kind: str, req: BaseModel | dict) -> str:
    body = req.model_dump(mode="json", exclude_none=True) if isinstance(req, BaseModel) else req
    return f"{kind}_" + hashlib.sha1(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]


def demo_or(kind: str, req, compute):
    if DEMO_MODE:
        f = DEMO_DIR / f"{key(kind, req)}.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))
    return compute()
