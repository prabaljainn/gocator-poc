"""Frame sources. Everything downstream consumes FrameSource and nothing else.

See docs/architecture.md. Adding live acquisition = adding one class here.
"""
from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import rec_reader as rr  # noqa: E402


@dataclass
class Frame:
    idx: int
    z16: np.ndarray      # int16 (H, W), rr.INVALID = no return
    intensity: np.ndarray  # uint8 (H, W), pixel-aligned with z16
    t_wall: float        # time.time() when the frame reached us
    # Live frames report their own spacing (it moves with the sensor's active-area
    # settings); None means "use the recording's constants".
    dx_mm: float | None = None
    dy_mm: float | None = None


@dataclass
class SourceHealth:
    kind: str
    connected: bool
    frames_seen: int
    detail: str = ""


class FrameSource(Protocol):
    def frames(self) -> Iterator[Frame]: ...
    def health(self) -> SourceHealth: ...


class ReplaySource:
    """Frames from a .rec file — real captured sensor data (D10: no simulated source).

    Works on both saved recordings and buffers pulled live off the sensor via
    command.cgi (docs/gocator-api.md).
    """

    def __init__(self, path: str | Path, limit: int | None = None):
        self.path = str(path)
        self.limit = limit
        self._seen = 0
        self._ends: list[int] | None = None

    def _load_index(self) -> list[int]:
        if self._ends is None:
            self._ends = rr.frame_ends(self.path)
        return self._ends

    def __len__(self) -> int:
        return len(self._load_index())

    def frames(self) -> Iterator[Frame]:
        ends = self._load_index()
        if self.limit is not None:
            ends = ends[: self.limit]
        _, _, dx_mm, dy_mm, _ = rr.get_rec_info(self.path)
        for i, end in enumerate(ends):
            z16, inten = rr.read_frame(self.path, end)
            self._seen = i + 1
            yield Frame(idx=i, z16=z16, intensity=inten, t_wall=time.time(),
                        dx_mm=dx_mm, dy_mm=dy_mm)

    def health(self) -> SourceHealth:
        return SourceHealth(
            kind="replay",
            connected=Path(self.path).exists(),
            frames_seen=self._seen,
            detail=Path(self.path).name,
        )


class SessionSource:
    """Frames from a recorded session directory — re-run past sessions through a
    newer detector. Mirrors Recorder's layout."""

    def __init__(self, session_dir: str | Path):
        self.dir = Path(session_dir)
        self._seen = 0

    def _files(self) -> list[Path]:
        return sorted((self.dir / "frames").glob("*.npz"))

    def frames(self) -> Iterator[Frame]:
        for i, f in enumerate(self._files()):
            with np.load(f) as d:
                z16, inten = d["z16"], d["intensity"]
            self._seen = i + 1
            yield Frame(idx=int(f.stem), z16=z16, intensity=inten, t_wall=time.time())

    def health(self) -> SourceHealth:
        return SourceHealth(
            kind="session",
            connected=self.dir.is_dir(),
            frames_seen=self._seen,
            detail=self.dir.name,
        )


class LiveSource:
    """Surfaces straight off the sensor via GoSDK (backend/app/gosdk.py).

    Configures the sensor as a side effect (Surface mode, intensity on,
    fixed-length generation, Ethernet sources) — without those it streams
    nothing at all.
    """

    def __init__(self, ip: str = "192.168.1.10", timeout_us: int = 20_000_000,
                 limit: int | None = None, reconnect: bool = True,
                 retry_wait: float = 3.0, max_retries: int | None = None):
        self.ip = ip
        self.timeout_us = timeout_us
        self.limit = limit
        self.reconnect = reconnect
        self.retry_wait = retry_wait
        self.max_retries = max_retries   # None = keep trying until the session stops
        self._seen = 0
        self._connected = False
        self._detail = ip
        self._stream = None
        self._attempt = 0
        self._last_error: str | None = None
        self._should_stop = lambda: False

    def set_stop_check(self, fn) -> None:
        """SessionRunner hands us its stop flag so a retry backoff doesn't outlive
        a stop() request."""
        self._should_stop = fn

    def _sleep_interruptibly(self, seconds: float) -> bool:
        """Returns False if we were asked to stop while waiting."""
        waited = 0.0
        while waited < seconds:
            if self._should_stop():
                return False
            time.sleep(0.25)
            waited += 0.25
        return True

    def frames(self) -> Iterator[Frame]:
        from .gosdk import GocatorStream  # imported lazily: needs the built SDK

        idx = 0
        while True:
            try:
                with GocatorStream(self.ip, self.timeout_us) as stream:
                    self._stream, self._connected = stream, True
                    self._attempt, self._last_error = 0, None
                    self._detail = f"{self.ip} (surface {stream.meta.get('surface_length_mm')}mm)"
                    try:
                        for z16, inten, meta in stream.frames():
                            if inten is None:
                                # the detector keys entirely on intensity texture
                                raise RuntimeError(
                                    "sensor sent no intensity — enable Surface Intensity output "
                                    f"(gosdk meta: {meta.get('intensity_source_error')})")
                            self._seen = idx + 1
                            yield Frame(idx=idx, z16=z16, intensity=inten, t_wall=time.time(),
                                        dx_mm=meta["x_res_nm"] / 1e6, dy_mm=meta["y_res_nm"] / 1e6)
                            idx += 1
                            # A live stream never ends on its own; without this a session
                            # started with a limit runs until someone stops it.
                            if self.limit is not None and idx >= self.limit:
                                return
                    finally:
                        self._connected = False
            except GeneratorExit:
                raise
            except Exception as e:
                # A cable pull surfaces here as GoSystem_ReceiveData kStatus -993.
                # Frames already yielded are on disk (D5); losing the rest of a field
                # pass because someone knocked a connector is the worse outcome.
                if self._should_stop():
                    # A stop landing while we were inside an SDK call is not a
                    # failure; re-raising here marked user-stopped sessions "error".
                    return
                if not self.reconnect:
                    raise
                if self.max_retries is not None and self._attempt >= self.max_retries:
                    raise
                self._attempt += 1
                self._last_error = f"{type(e).__name__}: {e}"
                self._detail = (f"{self.ip} — reconnecting (attempt {self._attempt}): "
                                f"{self._last_error}")
                if not self._sleep_interruptibly(self.retry_wait):
                    return
                # idx deliberately keeps counting: restarting at 0 would overwrite
                # the frames already recorded for this session.

    def health(self) -> SourceHealth:
        return SourceHealth(kind="live", connected=self._connected,
                            frames_seen=self._seen, detail=self._detail)
