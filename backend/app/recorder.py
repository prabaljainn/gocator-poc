"""Session recording. Invariant: the raw frame hits disk BEFORE detection runs
(docs/architecture.md, D5) — a detector crash must never cost field data."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

MIN_FREE_GB = 5.0


class DiskFullError(RuntimeError):
    pass


def free_gb(path: Path) -> float:
    return shutil.disk_usage(path).free / 1e9


class Recorder:
    """One session = one directory of raw frames + overlays + meta.json."""

    def __init__(self, root: str | Path, name: str, meta: dict | None = None):
        self.root = Path(root)
        self.dir = self.root / name
        (self.dir / "frames").mkdir(parents=True, exist_ok=True)
        (self.dir / "overlays").mkdir(parents=True, exist_ok=True)
        if free_gb(self.root) < MIN_FREE_GB:
            raise DiskFullError(f"{free_gb(self.root):.1f} GB free, need {MIN_FREE_GB}")
        self.meta = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "x_spacing_mm": None,  # filled from rec_reader constants by caller
            **(meta or {}),
        }
        self._write_meta()

    def _write_meta(self) -> None:
        (self.dir / "meta.json").write_text(json.dumps(self.meta, indent=2))

    def update_meta(self, **kw) -> None:
        """Overwrite meta fields mid-session — live frames only report their real
        spacing once the first surface arrives."""
        self.meta.update(kw)
        self._write_meta()

    def save_raw(self, idx: int, z16: np.ndarray, intensity: np.ndarray) -> Path:
        """Called before detection. Compressed npz keeps a field pass near 1-2 GB."""
        p = self.dir / "frames" / f"{idx:06d}.npz"
        tmp = p.with_name(p.name + ".tmp")
        # file handle, not a path: savez_compressed appends .npz to bare paths
        with open(tmp, "wb") as fh:
            np.savez_compressed(fh, z16=z16, intensity=intensity)
        tmp.replace(p)  # atomic: a half-written frame never looks complete
        return p

    def save_overlay(self, idx: int, img: np.ndarray) -> Path:
        p = self.dir / "overlays" / f"{idx:06d}.jpg"
        cv2.imwrite(str(p), img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return p

    def finalize(self, **extra) -> None:
        self.meta.update(ended_at=datetime.now(timezone.utc).isoformat(), **extra)
        self._write_meta()
