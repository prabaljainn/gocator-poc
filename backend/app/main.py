"""FastAPI service: REST + WebSocket + static frontend.

    uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import os
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .pipeline import SessionRunner
from .sources import ReplaySource, SessionSource
from .store import Store

REPO = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("GOCATOR_DATA", REPO / "data"))
SENSOR_IP = os.environ.get("GOCATOR_SENSOR", "192.168.1.10")

app = FastAPI(title="gocator-poc")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])  # ponytail: LAN-only tool; add auth if it leaves the bench

store = Store(DATA_ROOT / "gocator.sqlite")
current: SessionRunner | None = None


class Hub:
    """Fan-out to connected browsers. Events are fire-and-forget; the UI
    re-syncs over REST on reconnect."""

    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    async def join(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def drop(self, ws: WebSocket):
        self.clients.discard(ws)

    def emit(self, kind: str, payload: dict):
        """Callable from the pipeline's worker thread."""
        if not self.loop:
            return
        msg = {"type": kind, **payload}
        asyncio.run_coroutine_threadsafe(self._send(msg), self.loop)

    async def _send(self, msg: dict):
        for ws in list(self.clients):
            try:
                await ws.send_json(msg)
            except Exception:
                self.drop(ws)


hub = Hub()


@app.on_event("startup")
async def _startup():
    hub.loop = asyncio.get_running_loop()


class StartSession(BaseModel):
    mode: str = "replay"          # replay | session (live once GoSDK lands)
    source: str                   # .rec path, or session dir name
    notes: str = ""
    limit: int | None = None      # cap frames, handy for a quick pass


@app.post("/api/sessions")
def start_session(req: StartSession):
    global current
    if current and current.alive:
        raise HTTPException(409, "a session is already running")
    if req.mode == "replay":
        path = Path(req.source)
        if not path.is_absolute():
            path = REPO / req.source
        if not path.exists():
            raise HTTPException(404, f"no such .rec: {path}")
        src = ReplaySource(path, limit=req.limit)
    elif req.mode == "session":
        d = DATA_ROOT / "sessions" / req.source
        if not d.is_dir():
            raise HTTPException(404, f"no such session dir: {req.source}")
        src = SessionSource(d)
    else:
        raise HTTPException(400, f"unsupported mode {req.mode!r} "
                                 "(live acquisition needs GoSDK — docs/setup-dgx.md)")
    name = f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{req.mode}"
    current = SessionRunner(store, src, DATA_ROOT, name, req.mode, req.notes, hub.emit)
    current.start()
    hub.emit("session_state", {"session_id": current.session_id, "state": "running"})
    return {"session_id": current.session_id, "dir": name}


@app.post("/api/sessions/{sid}/stop")
def stop_session(sid: int):
    if current and current.session_id == sid and current.alive:
        current.stop()
        return {"stopping": True}
    raise HTTPException(404, "not the running session")


@app.get("/api/sessions")
def list_sessions():
    return store.sessions()


@app.get("/api/sessions/{sid}")
def get_session(sid: int):
    s = store.session(sid)
    if not s:
        raise HTTPException(404, "no such session")
    return s | {"heads": store.heads(sid)}


@app.get("/api/sessions/{sid}/heads")
def get_heads(sid: int, all: bool = False):
    return store.heads(sid, accepted_only=not all)


@app.get("/api/sessions/{sid}/overlay/{idx}.jpg")
def get_overlay(sid: int, idx: int):
    s = store.session(sid)
    if not s:
        raise HTTPException(404, "no such session")
    p = Path(s["dir"]) / "overlays" / f"{idx:06d}.jpg"
    if not p.exists():
        raise HTTPException(404, "no overlay for that frame")
    return FileResponse(p, media_type="image/jpeg")


class GroundTruth(BaseModel):
    session_id: int
    plant_tag: str
    caliper_mm: float
    head_id: int | None = None


@app.post("/api/ground-truth")
def add_ground_truth(gt: GroundTruth):
    return {"id": store.add_ground_truth(gt.session_id, gt.plant_tag,
                                         gt.caliper_mm, gt.head_id)}


@app.get("/api/sessions/{sid}/validation")
def validation(sid: int):
    return store.validation(sid)


@app.get("/api/health")
def health():
    du = shutil.disk_usage(DATA_ROOT if DATA_ROOT.exists() else REPO)
    running = bool(current and current.alive)
    return {
        "running": running,
        "session_id": current.session_id if current else None,
        "frames_done": current.frames_done if current else 0,
        "heads_found": current.heads_found if current else 0,
        "source": current.source.health().__dict__ if current else None,
        "disk_free_gb": round(du.free / 1e9, 1),
        "sensor_ip": SENSOR_IP,
        "live_acquisition": False,  # flips when the GoSDK LiveSource lands
    }


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await hub.join(ws)
    try:
        while True:
            await ws.receive_text()  # client keepalives; server is push-only
    except WebSocketDisconnect:
        hub.drop(ws)
    except Exception:
        hub.drop(ws)


_dist = REPO / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        """Serve the built file if it exists, else index.html so client-side
        routes like /sessions/2 survive a page load or a shared link."""
        if path.startswith("api/"):
            raise HTTPException(404, "no such endpoint")
        f = _dist / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(_dist / "index.html")
