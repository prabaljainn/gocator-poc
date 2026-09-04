"""SQLite store. Schema mirrors docs/architecture.md."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, ended_at TEXT,
    mode TEXT NOT NULL, source TEXT, dir TEXT, notes TEXT,
    state TEXT NOT NULL DEFAULT 'running');
CREATE TABLE IF NOT EXISTS frames (
    id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
    idx INTEGER NOT NULL, ts TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
    UNIQUE(session_id, idx));
CREATE TABLE IF NOT EXISTS heads (
    id INTEGER PRIMARY KEY, frame_id INTEGER NOT NULL REFERENCES frames(id),
    cx_mm REAL, cy_mm REAL, dia_mm REAL, tex_in REAL, valid_frac REAL,
    height_mm REAL, truncated INTEGER, accepted INTEGER);
CREATE TABLE IF NOT EXISTS ground_truth (
    id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
    plant_tag TEXT NOT NULL, caliper_mm REAL NOT NULL,
    matched_head_id INTEGER REFERENCES heads(id), created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_frames_session ON frames(session_id);
CREATE INDEX IF NOT EXISTS ix_heads_frame ON heads(frame_id);
"""

_now = lambda: datetime.now(timezone.utc).isoformat()  # noqa: E731


class Store:
    def __init__(self, db_path: str | Path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")  # survives an unclean shutdown
        self.db.executescript(SCHEMA)
        self.db.commit()

    # --- sessions ---
    def start_session(self, mode: str, source: str, dir: str, notes: str = "") -> int:
        cur = self.db.execute(
            "INSERT INTO sessions (started_at, mode, source, dir, notes) VALUES (?,?,?,?,?)",
            (_now(), mode, source, dir, notes))
        self.db.commit()
        return cur.lastrowid

    def stop_session(self, sid: int, state: str = "done") -> None:
        self.db.execute("UPDATE sessions SET ended_at=?, state=? WHERE id=?", (_now(), state, sid))
        self.db.commit()

    def sessions(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("""
            SELECT s.*, COUNT(DISTINCT f.id) AS frame_count,
                   COALESCE(SUM(h.accepted), 0) AS head_count
            FROM sessions s LEFT JOIN frames f ON f.session_id = s.id
            LEFT JOIN heads h ON h.frame_id = f.id
            GROUP BY s.id ORDER BY s.id DESC""")]

    def session(self, sid: int) -> dict | None:
        r = self.db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        return dict(r) if r else None

    # --- frames & heads ---
    def add_frame(self, sid: int, idx: int, status: str = "recorded") -> int:
        cur = self.db.execute(
            "INSERT OR REPLACE INTO frames (session_id, idx, ts, status) VALUES (?,?,?,?)",
            (sid, idx, _now(), status))
        self.db.commit()
        return cur.lastrowid

    def set_frame_status(self, fid: int, status: str, error: str | None = None) -> None:
        self.db.execute("UPDATE frames SET status=?, error=? WHERE id=?", (status, error, fid))
        self.db.commit()

    def add_heads(self, fid: int, heads: list[dict]) -> list[int]:
        # numpy scalars implement the buffer protocol, so sqlite3 would store them
        # as BLOBs and they'd come back as unencodable bytes — coerce to Python types.
        f = lambda v: None if v is None else float(v)  # noqa: E731
        ids = []
        for h in heads:
            cur = self.db.execute("""
                INSERT INTO heads (frame_id, cx_mm, cy_mm, dia_mm, tex_in, valid_frac,
                                   height_mm, truncated, accepted) VALUES (?,?,?,?,?,?,?,?,?)""",
                (fid, f(h.get("cx_mm")), f(h.get("cy_mm")), f(h.get("dia_mm")),
                 f(h.get("tex_in")), f(h.get("valid_frac")), f(h.get("height_mm")),
                 int(h.get("truncated", 0)), int(h.get("accepted", 0))))
            ids.append(cur.lastrowid)
        self.db.commit()
        return ids

    def heads(self, sid: int, accepted_only: bool = True) -> list[dict]:
        q = """SELECT h.*, f.idx AS frame_idx FROM heads h
               JOIN frames f ON f.id = h.frame_id WHERE f.session_id=?"""
        if accepted_only:
            q += " AND h.accepted=1"
        return [dict(r) for r in self.db.execute(q + " ORDER BY f.idx, h.id", (sid,))]

    # --- ground truth / validation ---
    def add_ground_truth(self, sid: int, plant_tag: str, caliper_mm: float,
                         head_id: int | None) -> int:
        cur = self.db.execute("""INSERT INTO ground_truth
            (session_id, plant_tag, caliper_mm, matched_head_id, created_at)
            VALUES (?,?,?,?,?)""", (sid, plant_tag, caliper_mm, head_id, _now()))
        self.db.commit()
        return cur.lastrowid

    def validation(self, sid: int) -> dict:
        rows = [dict(r) for r in self.db.execute("""
            SELECT g.plant_tag, g.caliper_mm, h.dia_mm AS ours_mm, f.idx AS frame_idx
            FROM ground_truth g LEFT JOIN heads h ON h.id = g.matched_head_id
            LEFT JOIN frames f ON f.id = h.frame_id
            WHERE g.session_id=? ORDER BY g.plant_tag""", (sid,))]
        paired = [r for r in rows if r["ours_mm"] is not None]
        errs = [r["ours_mm"] - r["caliper_mm"] for r in paired]
        stats = {"n": len(paired), "unmatched": len(rows) - len(paired)}
        if errs:
            stats.update({
                "mae_mm": sum(abs(e) for e in errs) / len(errs),
                "bias_mm": sum(errs) / len(errs),
                "max_abs_err_mm": max(abs(e) for e in errs),
            })
        return {"rows": rows, "stats": stats}
