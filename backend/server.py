"""Local token server + goals API + static frontend.

Run with:  .venv/bin/uvicorn backend.server:app --port 3000
"""

from __future__ import annotations

import os
import re
import secrets
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from livekit import api

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
load_dotenv(ROOT / ".env")

from backend.goals import GoalStore  # noqa: E402  (after load_dotenv)

LIVEKIT_URL = os.getenv("PUBLIC_LIVEKIT_URL") or os.getenv("LIVEKIT_URL", "ws://localhost:7880")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "devkey")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "secret")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

DEFAULT_ROOM = os.getenv("FAIRY_ROOM", "fairy-goals")
STORE = GoalStore(os.getenv("GOALS_DB", str(ROOT / "data" / "goals.db")))

app = FastAPI(title="My Fairy Goals", docs_url=None, redoc_url=None)


def _safe_identity(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", raw or "")[:64]
    return cleaned or f"dreamer-{secrets.token_hex(3)}"


def _safe_room(raw: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]", "", raw or "")[:64]
    if cleaned:
        return cleaned
    # Each browser session gets a fresh room. Automatic agent dispatch fires
    # when a room is created, so reusing one room name means a reconnect within
    # the server's empty-room timeout would join a room with no agent in it.
    return f"{DEFAULT_ROOM}-{secrets.token_hex(3)}"


def _key_configured() -> bool:
    return bool(GOOGLE_API_KEY and GOOGLE_API_KEY not in {"your-google-ai-studio-key", "PASTE_KEY_HERE"})


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "google_key_configured": _key_configured(),
        "livekit_url": LIVEKIT_URL,
        "room_prefix": DEFAULT_ROOM,
    }


@app.get("/api/token")
async def token(
    identity: str = Query("", max_length=64),
    room: str = Query("", max_length=64),
    name: str = Query("Dreamer", max_length=40),
) -> dict:
    identity = _safe_identity(identity)
    room = _safe_room(room)
    display_name = re.sub(r"[^\w \-'.]", "", name)[:40] or "Dreamer"

    if not LIVEKIT_API_KEY or not LIVEKIT_API_SECRET:
        raise HTTPException(status_code=500, detail="LiveKit API key/secret are not configured.")

    grants = api.VideoGrants(room_join=True, room=room)
    access_token = (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name(display_name)
        .with_grants(grants)
        .with_ttl(timedelta(hours=1))
    )

    return {
        "token": access_token.to_jwt(),
        "url": LIVEKIT_URL,
        "room": room,
        "identity": identity,
        "name": display_name,
    }


@app.get("/api/goals")
async def list_goals(identity: str = Query(..., max_length=64)) -> dict:
    identity = _safe_identity(identity)
    return {"goals": STORE.list(identity)}


@app.get("/api/check-ins")
async def list_check_ins(
    identity: str = Query(..., max_length=64),
    limit: int = Query(20, ge=1, le=100),
) -> dict:
    """Scheduled notes from Fae, newest first."""
    identity = _safe_identity(identity)
    return {"check_ins": STORE.list_check_ins(identity, limit)}


@app.post("/api/check-ins/run")
async def run_check_in(identity: str = Query("", max_length=64)) -> dict:
    """Trigger the Temporal check-in workflow now.

    Passing an identity limits the run to that dreamer; omitting it checks
    every dreamer, just like the daily schedule does.
    """
    target = _safe_identity(identity) if identity else None
    try:
        from backend.temporal.client import start_check_in

        workflow_id = await start_check_in(target)
    except Exception as exc:  # Temporal down / worker not ready
        raise HTTPException(
            status_code=503,
            detail=(
                "Temporal is not reachable. Start it with `make temporal-up` "
                "and the worker with `make temporal-worker`."
            ),
        ) from exc
    return {"ok": True, "workflow_id": workflow_id}


@app.post("/api/goals/{goal_id}/complete")
async def complete_goal(goal_id: str, identity: str = Query(..., max_length=64)) -> dict:
    identity = _safe_identity(identity)
    goal = STORE.complete(identity, goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found or already complete.")
    return {"goal": goal, "goals": STORE.list(identity)}


@app.delete("/api/goals/{goal_id}")
async def delete_goal(goal_id: str, identity: str = Query(..., max_length=64)) -> dict:
    identity = _safe_identity(identity)
    if not STORE.remove(identity, goal_id):
        raise HTTPException(status_code=404, detail="Goal not found.")
    return {"ok": True, "goals": STORE.list(identity)}


@app.exception_handler(500)
async def _server_error(_request, exc):  # pragma: no cover - defensive
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# Static site last so /api/* wins.
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
