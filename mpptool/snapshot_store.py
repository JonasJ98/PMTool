"""Historisierung: jeder Import wird als unveränderlicher Snapshot in SQLite abgelegt."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from . import config
from .model import Snapshot, TaskRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL,
    source_file   TEXT NOT NULL,
    label         TEXT NOT NULL DEFAULT '',
    imported_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    snapshot_id      INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    uid              TEXT NOT NULL,
    name             TEXT NOT NULL,
    department       TEXT NOT NULL,
    start            TEXT,
    finish           TEXT,
    baseline_finish  TEXT,
    actual_finish    TEXT,
    percent_complete REAL NOT NULL,
    is_summary       INTEGER NOT NULL,
    is_milestone     INTEGER NOT NULL,
    is_active        INTEGER NOT NULL,
    is_external      INTEGER NOT NULL,
    source_file      TEXT NOT NULL,
    outline_level    INTEGER NOT NULL,
    hold_flag        INTEGER NOT NULL,
    cancel_flag      INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (snapshot_id, uid)
);
CREATE INDEX IF NOT EXISTS ix_tasks_snapshot ON tasks(snapshot_id);
"""


def _d2s(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _s2d(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


class SnapshotStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else config.DB_PATH
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Spalten ergänzen, die in älteren Datenbanken noch fehlen."""
        try:
            self.conn.execute("ALTER TABLE tasks ADD COLUMN cancel_flag INTEGER NOT NULL DEFAULT 0")
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # Spalte existiert bereits

    # ------------------------------------------------------------------
    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "SnapshotStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------
    def add_snapshot(self, snap: Snapshot) -> int:
        imported_at = datetime.now().isoformat(timespec="seconds")
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO snapshots(snapshot_date, source_file, label, imported_at) VALUES (?,?,?,?)",
            (snap.snapshot_date.isoformat(), snap.source_file, snap.label, imported_at),
        )
        sid = cur.lastrowid
        cur.executemany(
            "INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(sid, t.uid, t.name, t.department, _d2s(t.start), _d2s(t.finish),
              _d2s(t.baseline_finish), _d2s(t.actual_finish), t.percent_complete,
              int(t.is_summary), int(t.is_milestone), int(t.is_active), int(t.is_external),
              t.source_file, t.outline_level, int(t.hold_flag), int(t.cancel_flag)) for t in snap.tasks],
        )
        self.conn.commit()
        snap.snapshot_id = sid
        snap.imported_at = imported_at
        return sid

    def list_snapshots(self) -> list[Snapshot]:
        rows = self.conn.execute(
            "SELECT id, snapshot_date, source_file, label, imported_at FROM snapshots "
            "ORDER BY snapshot_date, id"
        ).fetchall()
        return [Snapshot(snapshot_id=r[0], snapshot_date=date.fromisoformat(r[1]),
                         source_file=r[2], label=r[3], imported_at=r[4]) for r in rows]

    def load_snapshot(self, snapshot_id: int) -> Snapshot:
        r = self.conn.execute(
            "SELECT id, snapshot_date, source_file, label, imported_at FROM snapshots WHERE id=?",
            (snapshot_id,)).fetchone()
        if r is None:
            raise KeyError(f"Snapshot {snapshot_id} nicht vorhanden")
        snap = Snapshot(snapshot_id=r[0], snapshot_date=date.fromisoformat(r[1]),
                        source_file=r[2], label=r[3], imported_at=r[4])
        for t in self.conn.execute(
                "SELECT uid,name,department,start,finish,baseline_finish,actual_finish,"
                "percent_complete,is_summary,is_milestone,is_active,is_external,source_file,"
                "outline_level,hold_flag,cancel_flag FROM tasks WHERE snapshot_id=? ORDER BY uid", (snapshot_id,)):
            snap.tasks.append(TaskRecord(
                uid=t[0], name=t[1], department=t[2], start=_s2d(t[3]), finish=_s2d(t[4]),
                baseline_finish=_s2d(t[5]), actual_finish=_s2d(t[6]), percent_complete=t[7],
                is_summary=bool(t[8]), is_milestone=bool(t[9]), is_active=bool(t[10]),
                is_external=bool(t[11]), source_file=t[12], outline_level=t[13],
                hold_flag=bool(t[14]), cancel_flag=bool(t[15])))
        return snap

    def load_snapshots(self, ids: list[int]) -> list[Snapshot]:
        return sorted((self.load_snapshot(i) for i in ids), key=lambda s: (s.snapshot_date, s.snapshot_id))

    def delete_snapshot(self, snapshot_id: int) -> None:
        self.conn.execute("DELETE FROM snapshots WHERE id=?", (snapshot_id,))
        self.conn.commit()

    def clear(self) -> None:
        self.conn.execute("DELETE FROM snapshots")
        self.conn.commit()
