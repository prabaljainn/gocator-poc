"""Session pipeline: pull frames from a FrameSource, record, detect, store, broadcast.

Ordering is the point: save_raw() precedes detection (D5). Detector failures mark
the frame and continue — the raw data is already safe on disk.
"""
from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import detect  # noqa: E402
import rec_reader as rr  # noqa: E402

from .recorder import Recorder  # noqa: E402
from .sources import FrameSource  # noqa: E402
from .store import Store  # noqa: E402


class SessionRunner:
    """Runs one session on a worker thread. Stop with .stop()."""

    def __init__(self, store: Store, source: FrameSource, data_root: Path,
                 name: str, mode: str, notes: str = "", on_event=None):
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
        self.frames_done = 0
        self.heads_found = 0
        self.error: str | None = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

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
                # 1. raw to disk FIRST — nothing below may risk this data
                self.recorder.save_raw(frame.idx, frame.z16, frame.intensity)
                fid = self.store.add_frame(self.session_id, frame.idx, "recorded")

                # 2. detect; a failure costs this frame's results, never the frame
                try:
                    z_mm, inten, valid = detect.preprocess(frame.z16, frame.intensity)
                    heads = detect.find_heads(z_mm, inten, valid)
                    self.recorder.save_overlay(frame.idx, detect.overlay(inten, heads))
                    rows = [{k: v for k, v in h.items() if not k.startswith("_")} for h in heads]
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
                    self.on_event("frame_failed", {"session_id": self.session_id,
                                                   "frame_idx": frame.idx, "error": err})
                self.frames_done += 1
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
