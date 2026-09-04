"""FastAPI service: REST + WebSocket + static frontend.

    uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import json
import logging
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
from .sources import LiveSource, ReplaySource, SessionSource
from .store import Store
from .annotate import router as annotate_router
from .sensor import router as sensor_router, set_busy_check, reachable

log = logging.getLogger("gocator")
REPO = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("GOCATOR_DATA", REPO / "data"))
SENSOR_IP = os.environ.get("GOCATOR_SENSOR", "192.168.1.10")

app = FastAPI(title="gocator-poc")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])  # ponytail: LAN-only tool; add auth if it leaves the bench
app.include_router(annotate_router)
app.include_router(sensor_router)
# the control panel must not open a second SDK connection mid-session
set_busy_check(lambda: bool(current and current.alive))

store = Store(DATA_ROOT / "gocator.sqlite")
current: SessionRunner | None = None


class Hub:
    """Fan-out to connected browsers. Events are fire-and-forget; the UI
    re-syncs over REST on reconnect.

    All sends go through one queue drained by a single task: Starlette
    WebSockets do not tolerate concurrent writes, and the detector thread
    emits faster than a socket drains — writing directly from many
    run_coroutine_threadsafe callbacks corrupts the connection after a few
    frames and the UI silently stops updating.
    """

    QUEUE_MAX = 256

    def __init__(self):
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.queue: asyncio.Queue | None = None
        self.dropped = 0

    async def start(self):
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue(maxsize=self.QUEUE_MAX)
        asyncio.create_task(self._drain())

    async def join(self, ws: WebSocket):
        await ws.accept()
        self.clients.add(ws)

    def drop(self, ws: WebSocket):
        self.clients.discard(ws)

    def emit(self, kind: str, payload: dict):
        """Callable from the pipeline's worker thread."""
        if not self.loop or not self.queue:
            return
        msg = {"type": kind, **payload}
        self.loop.call_soon_threadsafe(self._offer, msg)

    def _offer(self, msg: dict):
        try:
            self.queue.put_nowait(msg)
        except asyncio.QueueFull:
            self.dropped += 1  # a stalled browser must never stall detection

    async def _drain(self):
        while True:
            msg = await self.queue.get()
            await self._send(msg)

    async def _send(self, msg: dict):
        # Serialise once, up front: an unserialisable payload is a bug in us, and
        # must not be mistaken for dead clients and silently drop every browser.
        try:
            text = json.dumps(msg)
        except TypeError:
            log.exception("un-serialisable WS payload (type=%s) — event dropped",
                          msg.get("type"))
            return
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                self.drop(ws)


hub = Hub()


HEARTBEAT_S = 10


@app.on_event("startup")
async def _startup():
    await hub.start()

    async def beat():
        """Clients detect a half-open socket by the absence of these — without a
        server heartbeat a severed connection still reads as OPEN and the UI
        silently freezes until someone reloads."""
        while True:
            await asyncio.sleep(HEARTBEAT_S)
            await hub._send({"type": "heartbeat"})

    asyncio.create_task(beat())


class StartSession(BaseModel):
    mode: str = "replay"          # replay | session (live once GoSDK lands)
    source: str                   # .rec path, or session dir name
    notes: str = ""
    limit: int | None = None      # cap frames, handy for a quick pass
    fps: float = 2.0              # default 2 FPS for observable playback, 0 = uncapped


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
    elif req.mode == "live":
        src = LiveSource(req.source or SENSOR_IP, limit=req.limit)
    else:
        raise HTTPException(400, f"unsupported mode {req.mode!r}")
    name = f"{datetime.now().strftime('%Y-%m-%d_%H%M%S')}_{req.mode}"
    current = SessionRunner(store, src, DATA_ROOT, name, req.mode, req.notes, hub.emit, fps=req.fps)
    current.start()
    hub.emit("session_state", {"session_id": current.session_id, "state": "running"})
    return {"session_id": current.session_id, "dir": name}


@app.post("/api/sessions/{sid}/stop")
def stop_session(sid: int):
    if current and current.session_id == sid and current.alive:
        current.stop()
        return {"stopping": True}
    raise HTTPException(404, "not the running session")


@app.post("/api/sessions/{sid}/pause")
def pause_session(sid: int):
    if current and current.session_id == sid and current.alive:
        current.pause()
        return {"paused": True}
    raise HTTPException(404, "not the running session")


@app.post("/api/sessions/{sid}/resume")
def resume_session(sid: int):
    if current and current.session_id == sid and current.alive:
        current.resume()
        return {"resumed": True}
    raise HTTPException(404, "not the running session")


@app.post("/api/sessions/{sid}/step")
def step_session(sid: int):
    if current and current.session_id == sid and current.alive:
        current.step()
        return {"stepped": True}
    raise HTTPException(404, "not the running session")


class SetSpeedRequest(BaseModel):
    fps: float


@app.post("/api/sessions/{sid}/speed")
def set_speed(sid: int, req: SetSpeedRequest):
    if current and current.session_id == sid and current.alive:
        current.set_fps(req.fps)
        return {"fps": current.fps}
    raise HTTPException(404, "not the running session")


@app.get("/api/sessions")
def list_sessions():
    return store.sessions()


@app.get("/api/sessions/{sid}")
def get_session(sid: int):
    s = store.session(sid)
    if not s:
        raise HTTPException(404, "no such session")
    return {**s, "heads": store.heads(sid)}


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
        "paused": bool(current and current.is_paused),
        "fps": current.fps if current else 2.0,
        "session_id": current.session_id if current else None,
        "frames_done": current.frames_done if current else 0,
        "heads_found": current.heads_found if current else 0,
        "source": current.source.health().__dict__ if current else None,
        "disk_free_gb": round(du.free / 1e9, 1),
        "sensor_ip": SENSOR_IP,
        # can we do live at all (SDK present) vs is the sensor actually there
        "live_acquisition": _gosdk_available(),
        "sensor_reachable": reachable(),
    }


def _gosdk_available() -> bool:
    """True when the GoSDK libs are present and loadable, so the UI can offer
    live mode instead of failing at session start."""
    try:
        from .gosdk import _Lib
        _Lib()
        return True
    except Exception:
        return False


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
        return FileResponse(
            _dist / "index.html",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}
        )
