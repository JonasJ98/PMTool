"""Statuslogik und Kennzahlen.

Statusregeln (Stichtag = Snapshot-Datum):
  Hold            – Aufgabe inaktiv (Active = Nein) oder Hold-Textfeld gesetzt
  Closed          – abgeschlossen, tatsächliches Ende <= Referenzende
  Closed Overdue  – abgeschlossen, tatsächliches Ende >  Referenzende
  Open            – nicht abgeschlossen, geplantes Ende >= Stichtag
  Open Overdue    – nicht abgeschlossen, geplantes Ende <  Stichtag

Referenzende = Basisplan-Ende, sonst geplantes Ende.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

from . import config
from .model import Snapshot, TaskRecord, TaskStatus


# --------------------------------------------------------------------------
# Filter & Normalisierung
# --------------------------------------------------------------------------
def canonical_department(name: str | None) -> str:
    name = (name or "").strip()
    if not name:
        return config.DEPARTMENT_UNKNOWN
    return config.DEPARTMENT_ALIASES.get(name, name)


def relevant_tasks(tasks: list[TaskRecord]) -> list[TaskRecord]:
    out = []
    for t in tasks:
        if config.EXCLUDE_SUMMARY_TASKS and t.is_summary:
            continue
        if config.EXCLUDE_MILESTONES and t.is_milestone:
            continue
        if config.EXCLUDE_EXTERNAL_PLACEHOLDERS and t.is_external:
            continue
        out.append(t)
    return out


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------
def classify(task: TaskRecord, as_of: date) -> TaskStatus:
    if (config.USE_NATIVE_ACTIVE_FLAG_FOR_HOLD and not task.is_active) or task.hold_flag:
        return TaskStatus.HOLD
    reference_finish = task.baseline_finish or task.finish
    if task.is_complete:
        actual = task.actual_finish or task.finish
        if reference_finish and actual and actual > reference_finish:
            return TaskStatus.CLOSED_OVERDUE
        return TaskStatus.CLOSED
    if task.finish and task.finish < as_of:
        return TaskStatus.OPEN_OVERDUE
    return TaskStatus.OPEN


# --------------------------------------------------------------------------
# Kennzahlen je Snapshot
# --------------------------------------------------------------------------
@dataclass
class DepartmentStats:
    department: str
    counts: Counter = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    def n(self, status: TaskStatus) -> int:
        return self.counts.get(status, 0)

    @property
    def open_total(self) -> int:
        return self.n(TaskStatus.OPEN) + self.n(TaskStatus.OPEN_OVERDUE)

    @property
    def overdue_total(self) -> int:
        return self.n(TaskStatus.OPEN_OVERDUE) + self.n(TaskStatus.CLOSED_OVERDUE)


@dataclass
class SnapshotMetrics:
    snapshot: Snapshot
    as_of: date
    statuses: dict[str, TaskStatus]                   # uid -> status
    by_department: dict[str, DepartmentStats]
    monitored: int            # betrachtete Aufgaben gesamt
    planned_closed: int       # laut Plan bis Stichtag geschlossen
    actually_closed: int      # tatsächlich geschlossen
    open_overdue: int
    closed_overdue: int
    hold: int

    @property
    def fulfilment_pct(self) -> float:
        """Erfüllungsgrad: tatsächlich geschlossen / planmäßig geschlossen."""
        if self.planned_closed == 0:
            return 100.0 if self.actually_closed == 0 else 100.0
        return round(100.0 * self.actually_closed / self.planned_closed, 1)

    @property
    def overdue_total(self) -> int:
        return self.open_overdue

    @property
    def departments(self) -> list[str]:
        return sorted(self.by_department)

    def overdue_by_department(self) -> dict[str, int]:
        return {d: s.n(TaskStatus.OPEN_OVERDUE) for d, s in self.by_department.items()}

    def open_by_department(self) -> dict[str, int]:
        return {d: s.open_total for d, s in self.by_department.items()}


def compute_metrics(snapshot: Snapshot, as_of: date | None = None) -> SnapshotMetrics:
    as_of = as_of or snapshot.snapshot_date
    tasks = relevant_tasks(snapshot.tasks)
    statuses: dict[str, TaskStatus] = {}
    by_dep: dict[str, DepartmentStats] = {}
    planned_closed = actually_closed = open_overdue = closed_overdue = hold = 0

    for t in tasks:
        st = classify(t, as_of)
        statuses[t.uid] = st
        dep = canonical_department(t.department)
        by_dep.setdefault(dep, DepartmentStats(dep)).counts[st] += 1

        ref = t.baseline_finish or t.finish
        if ref and ref <= as_of and st != TaskStatus.HOLD:
            planned_closed += 1
        if st.is_closed:
            actually_closed += 1
        if st == TaskStatus.OPEN_OVERDUE:
            open_overdue += 1
        elif st == TaskStatus.CLOSED_OVERDUE:
            closed_overdue += 1
        elif st == TaskStatus.HOLD:
            hold += 1

    return SnapshotMetrics(
        snapshot=snapshot, as_of=as_of, statuses=statuses, by_department=by_dep,
        monitored=len(tasks), planned_closed=planned_closed,
        actually_closed=actually_closed, open_overdue=open_overdue,
        closed_overdue=closed_overdue, hold=hold,
    )


# --------------------------------------------------------------------------
# Vergleich zwischen Snapshots
# --------------------------------------------------------------------------
@dataclass
class OverdueTrendRow:
    department: str
    previous: int
    current: int

    @property
    def delta(self) -> int:
        return self.current - self.previous

    @property
    def arrow(self) -> str:
        if self.delta > 0:
            return "▲"   # mehr überfällig = schlechter
        if self.delta < 0:
            return "▼"
        return "►"


def overdue_trend(previous: SnapshotMetrics | None, current: SnapshotMetrics,
                  top_n: int | None = None) -> list[OverdueTrendRow]:
    """Top-N Abteilungen nach aktuell überfälligen Aufgaben, mit Vorwoche."""
    top_n = top_n or config.TOP_N_OVERDUES
    cur = current.overdue_by_department()
    prev = previous.overdue_by_department() if previous else {}
    deps = set(cur) | set(prev)
    rows = [OverdueTrendRow(d, prev.get(d, 0), cur.get(d, 0)) for d in deps]
    rows.sort(key=lambda r: (-r.current, -r.previous, r.department))
    return [r for r in rows[:top_n] if r.current or r.previous]


@dataclass
class TimelinePoint:
    snapshot_date: date
    label: str
    monitored: int
    planned_closed: int
    actually_closed: int
    fulfilment_pct: float
    overdue: int


def timeline(metrics_list: list[SnapshotMetrics]) -> list[TimelinePoint]:
    pts = []
    for m in sorted(metrics_list, key=lambda m: m.as_of):
        kw = m.as_of.isocalendar()[1]
        pts.append(TimelinePoint(
            snapshot_date=m.as_of, label=f"KW{kw:02d}", monitored=m.monitored,
            planned_closed=m.planned_closed, actually_closed=m.actually_closed,
            fulfilment_pct=m.fulfilment_pct, overdue=m.open_overdue,
        ))
    return pts


def task_changes(previous: SnapshotMetrics | None, current: SnapshotMetrics) -> dict[str, list[TaskRecord]]:
    """Neu überfällig / neu geschlossen / neu hinzugekommen seit Vorwoche."""
    cur_tasks = {t.uid: t for t in relevant_tasks(current.snapshot.tasks)}
    prev_status = previous.statuses if previous else {}
    newly_overdue, newly_closed, added = [], [], []
    for uid, t in cur_tasks.items():
        st = current.statuses[uid]
        ps = prev_status.get(uid)
        if ps is None and previous is not None:
            added.append(t)
        if st == TaskStatus.OPEN_OVERDUE and ps != TaskStatus.OPEN_OVERDUE:
            newly_overdue.append(t)
        if st.is_closed and (ps is None or not ps.is_closed):
            newly_closed.append(t)
    return {"newly_overdue": newly_overdue, "newly_closed": newly_closed, "added": added}


def overdue_tasks(m: SnapshotMetrics) -> list[TaskRecord]:
    tasks = {t.uid: t for t in relevant_tasks(m.snapshot.tasks)}
    rows = [tasks[u] for u, s in m.statuses.items() if s == TaskStatus.OPEN_OVERDUE]
    rows.sort(key=lambda t: (t.finish or date.max, canonical_department(t.department), t.name))
    return rows
