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
        for i, end in enumerate(ends):
            z16, inten = rr.read_frame(self.path, end)
            self._seen = i + 1
            yield Frame(idx=i, z16=z16, intensity=inten, t_wall=time.time())

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

    def __init__(self, ip: str = "192.168.1.10", timeout_us: int = 20_000_000):
        self.ip = ip
        self.timeout_us = timeout_us
        self._seen = 0
        self._connected = False
        self._detail = ip
        self._stream = None

    def frames(self) -> Iterator[Frame]:
        from .gosdk import GocatorStream  # imported lazily: needs the built SDK

        with GocatorStream(self.ip, self.timeout_us) as stream:
            self._stream, self._connected = stream, True
            self._detail = f"{self.ip} (surface {stream.meta.get('surface_length_mm')}mm)"
            try:
                for i, (z16, inten, meta) in enumerate(stream.frames()):
                    if inten is None:
                        # the detector keys entirely on intensity texture
                        raise RuntimeError(
                            "sensor sent no intensity — enable Surface Intensity output "
                            f"(gosdk meta: {meta.get('intensity_source_error')})")
                    self._seen = i + 1
                    yield Frame(idx=i, z16=z16, intensity=inten, t_wall=time.time(),
                                dx_mm=meta["x_res_nm"] / 1e6, dy_mm=meta["y_res_nm"] / 1e6)
            finally:
                self._connected = False

    def health(self) -> SourceHealth:
        return SourceHealth(kind="live", connected=self._connected,
                            frames_seen=self._seen, detail=self._detail)
