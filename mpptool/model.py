"""Datenmodell: Aufgabenzeile und Snapshot."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class TaskStatus(str, Enum):
    OPEN = "Open"
    OPEN_OVERDUE = "Open Overdue"
    CLOSED = "Closed"
    CLOSED_OVERDUE = "Closed Overdue"
    HOLD = "Hold"

    @property
    def is_open(self) -> bool:
        return self in (TaskStatus.OPEN, TaskStatus.OPEN_OVERDUE)

    @property
    def is_closed(self) -> bool:
        return self in (TaskStatus.CLOSED, TaskStatus.CLOSED_OVERDUE)

    @property
    def is_overdue(self) -> bool:
        return self in (TaskStatus.OPEN_OVERDUE, TaskStatus.CLOSED_OVERDUE)


@dataclass
class TaskRecord:
    """Eine Aufgabenzeile, formatunabhängig (aus .mpp/.xml oder synthetisch)."""

    uid: str                      # eindeutig über Master + Unterdatei
    name: str
    department: str
    start: date | None
    finish: date | None           # geplantes Ende (aktueller Plan)
    baseline_finish: date | None  # Basisplan-Ende, falls vorhanden
    actual_finish: date | None
    percent_complete: float
    is_summary: bool = False
    is_milestone: bool = False
    is_active: bool = True
    is_external: bool = False
    source_file: str = ""         # Dateiname (Master oder Unterdatei)
    outline_level: int = 1
    hold_flag: bool = False       # aus Textfeld, falls konfiguriert

    @property
    def is_complete(self) -> bool:
        return self.percent_complete >= 100 or self.actual_finish is not None


@dataclass
class Snapshot:
    """Ein Import = ein unveränderlicher, datierter Datensatz."""

    snapshot_date: date
    source_file: str
    tasks: list[TaskRecord] = field(default_factory=list)
    snapshot_id: int | None = None
    label: str = ""
    imported_at: str = ""

    @property
    def display_name(self) -> str:
        kw = self.snapshot_date.isocalendar()[1]
        base = f"KW{kw:02d} {self.snapshot_date.isoformat()}"
        return f"{base} – {self.label}" if self.label else base
