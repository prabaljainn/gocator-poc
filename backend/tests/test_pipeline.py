"""Backend checks. Run: .venv/bin/python -m backend.tests.test_pipeline

No pytest dependency — asserts + a __main__, matching detect.py --selftest.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import rec_reader as rr  # noqa: E402
from backend.app.pipeline import SessionRunner  # noqa: E402
from backend.app.recorder import Recorder  # noqa: E402
from backend.app.sources import Frame, SessionSource, SourceHealth  # noqa: E402
from backend.app.store import Store  # noqa: E402

# raw px are anisotropic and sub-mm, so the canvas must be sized in mm, not px:
# a 100 mm disc spans ~800 raw px in X. Same geometry as detect.py --selftest.
H, W = 1400, 2000
DISC_DIA_MM = 100.0


def _synthetic_frame(idx: int) -> Frame:
    """A textured disc on flat ground — the same shape detect.py --selftest uses."""
    z16 = np.full((H, W), 1000, np.int16)
    inten = np.full((H, W), 30, np.uint8)
    yy, xx = np.ogrid[:H, :W]
    disc = (((xx - W // 2) * rr.DX_MM) ** 2
            + ((yy - H // 2) * rr.DY_MM) ** 2) <= (DISC_DIA_MM / 2) ** 2
    z16[disc] = 5000
    inten[disc] = np.random.default_rng(idx).integers(40, 240, int(disc.sum()), dtype=np.uint8)
    return Frame(idx=idx, z16=z16, intensity=inten, t_wall=0.0)


class _FakeSource:
    """Emits N synthetic frames; frame `boom` carries garbage that breaks detection."""

    def __init__(self, n=3, boom=None):
        self.n, self.boom, self.seen = n, boom, 0

    def frames(self):
        for i in range(self.n):
            self.seen = i + 1
            f = _synthetic_frame(i)
            if i == self.boom:
                f.intensity = "not an array"  # type: ignore[assignment]
            yield f

    def health(self):
        return SourceHealth("fake", True, self.seen, "synthetic")


def test_recorder_roundtrip(tmp: Path):
    rec = Recorder(tmp / "sessions", "s1")
    z = np.arange(100, dtype=np.int16).reshape(10, 10)
    i = np.arange(100, dtype=np.uint8).reshape(10, 10)
    rec.save_raw(7, z, i)
    (frame,) = list(SessionSource(rec.dir).frames())
    assert np.array_equal(frame.z16, z), "z16 changed across write/read"
    assert np.array_equal(frame.intensity, i), "intensity changed across write/read"
    assert frame.idx == 7
    print("  ok  recorder round-trip is lossless")


def test_pipeline_detects_and_stores(tmp: Path):
    store = Store(tmp / "db.sqlite")
    runner = SessionRunner(store, _FakeSource(n=3), tmp, "s2", "test")
    runner.start()
    runner.join(timeout=60)
    assert not runner.alive, "runner did not finish"
    assert runner.frames_done == 3, f"processed {runner.frames_done}/3 frames"
    assert runner.heads_found >= 3, f"expected >=3 heads, got {runner.heads_found}"
    heads = store.heads(runner.session_id)
    assert len(heads) >= 3 and all(h["dia_mm"] > 0 for h in heads)
    assert store.session(runner.session_id)["state"] == "done"
    # numpy scalars must not land as BLOBs — they come back as unencodable bytes
    for k in ("cx_mm", "cy_mm", "dia_mm", "tex_in", "valid_frac", "height_mm"):
        assert isinstance(heads[0][k], float), f"{k} stored as {type(heads[0][k]).__name__}"
    import json
    json.dumps(heads)  # must be JSON-serialisable for the API
    print(f"  ok  pipeline: 3 frames → {len(heads)} heads stored, JSON-clean")


def test_ws_events_are_json_serialisable(tmp: Path):
    """Head payloads carry numpy scalars; if they reach the socket unconverted
    the send throws and every browser gets dropped mid-session."""
    import json
    store = Store(tmp / "db_ws.sqlite")
    events: list[tuple[str, dict]] = []
    runner = SessionRunner(store, _FakeSource(n=2), tmp, "s_ws", "test",
                           on_event=lambda k, p: events.append((k, p)))
    runner.start()
    runner.join(timeout=60)
    frames = [p for k, p in events if k == "frame_processed"]
    assert frames, "no frame_processed events emitted"
    assert any(f["heads"] for f in frames), "no event carried heads — test is vacuous"
    for k, p in events:
        json.dumps({"type": k, **p})  # raises TypeError on numpy scalars
    print(f"  ok  {len(events)} WS events JSON-serialisable (heads included)")


def test_raw_survives_detector_failure(tmp: Path):
    """The D5 invariant: a detector crash must not cost the raw frame."""
    store = Store(tmp / "db2.sqlite")
    runner = SessionRunner(store, _FakeSource(n=3, boom=1), tmp, "s3", "test")
    runner.start()
    runner.join(timeout=60)
    assert runner.frames_done == 3, "pipeline stopped on a detector failure"
    saved = sorted(p.stem for p in (runner.recorder.dir / "frames").glob("*.npz"))
    assert saved == ["000000", "000001", "000002"], f"raw frames lost: {saved}"
    rows = {r["idx"]: r["status"] for r in
            store.db.execute("SELECT idx, status FROM frames WHERE session_id=?",
                             (runner.session_id,))}
    assert rows[1] == "failed", f"frame 1 status {rows[1]!r}, expected 'failed'"
    assert rows[0] == rows[2] == "detected"
    print("  ok  raw frame survives detector failure (D5 invariant holds)")


def test_validation_math(tmp: Path):
    store = Store(tmp / "db3.sqlite")
    sid = store.start_session("test", "x", "d")
    fid = store.add_frame(sid, 0)
    (h1, h2) = store.add_heads(fid, [
        {"dia_mm": 72.0, "accepted": 1}, {"dia_mm": 80.0, "accepted": 1}])
    store.add_ground_truth(sid, "A1", 70.0, h1)   # +2.0
    store.add_ground_truth(sid, "A2", 84.0, h2)   # -4.0
    store.add_ground_truth(sid, "A3", 60.0, None)  # unmatched
    v = store.validation(sid)
    assert v["stats"]["n"] == 2 and v["stats"]["unmatched"] == 1
    assert abs(v["stats"]["mae_mm"] - 3.0) < 1e-9, v["stats"]
    assert abs(v["stats"]["bias_mm"] - (-1.0)) < 1e-9, v["stats"]
    assert abs(v["stats"]["max_abs_err_mm"] - 4.0) < 1e-9
    print("  ok  validation math (MAE 3.0, bias -1.0)")


def test_replay_reads_real_rec(rec_path: Path):
    from backend.app.sources import ReplaySource
    src = ReplaySource(rec_path, limit=1)
    (f,) = list(src.frames())
    assert f.z16.shape == (rr.H, rr.W), f.z16.shape
    assert f.intensity.shape == (rr.H, rr.W)
    valid = (f.z16 != rr.INVALID).mean()
    assert 0.01 < valid < 0.99, f"implausible valid fraction {valid:.2%}"
    print(f"  ok  ReplaySource on real .rec (frame 0, {valid:.1%} valid)")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        test_recorder_roundtrip(tmp)
        test_pipeline_detects_and_stores(tmp)
        test_ws_events_are_json_serialisable(tmp)
        test_raw_survives_detector_failure(tmp)
        test_validation_math(tmp)
    rec = next((p for p in [Path("tobetsu-data-20260730-1416.rec"),
                            Path.home() / "gocator-poc/tobetsu-data-20260730-1416.rec"]
                if p.exists()), None)
    if rec:
        test_replay_reads_real_rec(rec)
    else:
        print("  ..  skipped real .rec test (file not present)")
    print("backend selftest ok")
