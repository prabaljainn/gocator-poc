"""Session pipeline: pull frames from a FrameSource, record, detect, store, broadcast.

Ordering is the point: save_raw() precedes detection (D5). Detector failures mark
the frame and continue — the raw data is already safe on disk.
"""
from __future__ import annotations

import sys
import threading
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import detect  # noqa: E402
import rec_reader as rr  # noqa: E402

from . import ml_detector  # noqa: E402
from .recorder import Recorder  # noqa: E402
from .sources import FrameSource  # noqa: E402
from .store import Store  # noqa: E402


class SessionRunner:
    """Runs one session on a worker thread. Stop with .stop()."""

    def __init__(self, store: Store, source: FrameSource, data_root: Path,
                 name: str, mode: str, notes: str = "", on_event=None, fps: float = 2.0):
        self.store, self.source = store, source
        self.on_event = on_event or (lambda *_: None)
        self.recorder = Recorder(data_root / "sessions", name, meta={
            "mode": mode,
            "source": source.health().detail,
            "x_spacing_mm": rr.DX_MM,
            "y_spacing_mm": rr.DY_MM,
            "px_mm_working": detect.PX_MM,
        })
        self.session_id = store.start_session(mode, source.health().detail,
                                              str(self.recorder.dir), notes)
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._step = threading.Event()
        self.fps = fps
        self.frames_done = 0
        self.heads_found = 0
        self.error: str | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def pause(self) -> None:
        self._pause.set()
        self.on_event("session_state", {"session_id": self.session_id, "state": "paused"})

    def resume(self) -> None:
        self._pause.clear()
        self.on_event("session_state", {"session_id": self.session_id, "state": "running"})

    def step(self) -> None:
        self._step.set()

    def set_fps(self, fps: float) -> None:
        self.fps = max(0.0, fps)

    @property
    def is_paused(self) -> bool:
        return self._pause.is_set()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout)

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        state = "done"
        try:
            for frame in self.source.frames():
                if self._stop.is_set():
                    state = "stopped"
                    break

                # Handle pause and stepping
                while self._pause.is_set() and not self._stop.is_set():
                    if self._step.is_set():
                        self._step.clear()
                        break
                    time.sleep(0.04)

                if self._stop.is_set():
                    state = "stopped"
                    break

                t_start = time.time()
                # 1. raw to disk FIRST — nothing below may risk this data
                self.recorder.save_raw(frame.idx, frame.z16, frame.intensity)
                fid = self.store.add_frame(self.session_id, frame.idx, "recorded")

                # 2. detect; a failure costs this frame's results, never the frame
                try:
                    # live frames carry their own resolution; replay falls back
                    # to the recording's constants
                    z_mm, inten, valid, px_mm = detect.preprocess(
                        frame.z16, frame.intensity,
                        **{k: v for k, v in (("dx_mm", frame.dx_mm),
                                             ("dy_mm", frame.dy_mm)) if v})
                    heads = ml_detector.find_heads(z_mm, inten, valid, px_mm)
                    self.recorder.save_overlay(frame.idx, detect.overlay(inten, heads))
                    # numpy scalars aren't JSON-serialisable; without this the first
                    # frame carrying heads kills the WebSocket send (and the client).
                    rows = [{k: (v.item() if hasattr(v, "item") else v)
                             for k, v in h.items() if not k.startswith("_")} for h in heads]
                    self.store.add_heads(fid, rows)
                    self.store.set_frame_status(fid, "detected")
                    accepted = [r for r in rows if r["accepted"]]
                    self.heads_found += len(accepted)
                    self.on_event("frame_processed", {
                        "session_id": self.session_id, "frame_idx": frame.idx,
                        "heads": accepted, "n_candidates": len(rows),
                        "overlay_url": f"/api/sessions/{self.session_id}/overlay/{frame.idx}.jpg",
                        "totals": {"frames": self.frames_done + 1, "heads": self.heads_found},
                    })
                except Exception:
                    err = traceback.format_exc(limit=3)
                    self.store.set_frame_status(fid, "failed", err)
                self.frames_done += 1

                # Dynamic FPS pacing (0 = max speed/uncapped)
                if self.fps > 0:
                    elapsed = time.time() - t_start
                    delay = (1.0 / self.fps) - elapsed
                    if delay > 0:
                        t_end = time.time() + delay
                        while time.time() < t_end and not self._stop.is_set():
                            if self._pause.is_set():
                                break
                            time.sleep(min(0.03, max(0.001, t_end - time.time())))
        except Exception:
            self.error = traceback.format_exc(limit=5)
            state = "error"
        finally:
            self.recorder.finalize(frames=self.frames_done, heads=self.heads_found,
                                   state=state, error=self.error)
            self.store.stop_session(self.session_id, state)
            self.on_event("session_state", {"session_id": self.session_id, "state": state,
                                            "frames": self.frames_done,
                                            "heads": self.heads_found})
