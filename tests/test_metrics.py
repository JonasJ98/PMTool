from datetime import date

from mpptool import metrics
from mpptool.model import Snapshot, TaskRecord, TaskStatus

AS_OF = date(2026, 9, 4)


def task(uid, finish, pct=0.0, baseline=None, actual=None, active=True, summary=False, dep="AA"):
    return TaskRecord(uid=uid, name=f"T{uid}", department=dep, start=date(2026, 8, 1), finish=finish,
                      baseline_finish=baseline, actual_finish=actual, percent_complete=pct,
                      is_active=active, is_summary=summary)


def test_status_classification():
    assert metrics.classify(task("1", date(2026, 9, 10)), AS_OF) == TaskStatus.OPEN
    assert metrics.classify(task("2", date(2026, 9, 1)), AS_OF) == TaskStatus.OPEN_OVERDUE
    assert metrics.classify(task("3", date(2026, 9, 1), 100, actual=date(2026, 9, 1)), AS_OF) == TaskStatus.CLOSED
    assert metrics.classify(task("4", date(2026, 9, 3), 100, baseline=date(2026, 9, 1), actual=date(2026, 9, 3)), AS_OF) == TaskStatus.CLOSED_OVERDUE
    assert metrics.classify(task("5", date(2026, 9, 1), active=False), AS_OF) == TaskStatus.HOLD


def test_metrics_counts_and_summary_filter():
    snap = Snapshot(snapshot_date=AS_OF, source_file="x.mpp", tasks=[
        task("1", date(2026, 9, 10)),
        task("2", date(2026, 9, 1), dep="SW"),
        task("3", date(2026, 9, 1), 100, actual=date(2026, 9, 1)),
        task("4", date(2026, 9, 1), summary=True),
        task("5", date(2026, 9, 1), active=False),
    ])
    m = metrics.compute_metrics(snap)
    assert m.monitored == 4
    assert m.planned_closed == 2          # #2 und #3 (Hold zählt nicht)
    assert m.actually_closed == 1
    assert m.open_overdue == 1
    assert m.hold == 1
    assert m.fulfilment_pct == 50.0
    assert m.overdue_by_department() == {"AA": 0, "SW": 1}


def test_department_alias(monkeypatch):
    from mpptool import config
    monkeypatch.setattr(config, "DEPARTMENT_ALIASES", {"Purchasing": "PUR"})
    assert metrics.canonical_department("Purchasing") == "PUR"
    assert metrics.canonical_department("") == config.DEPARTMENT_UNKNOWN


def test_overdue_trend_and_changes():
    prev = Snapshot(snapshot_date=date(2026, 8, 28), source_file="a", tasks=[
        task("1", date(2026, 8, 20), dep="SW"), task("2", date(2026, 9, 10), dep="AA")])
    cur = Snapshot(snapshot_date=AS_OF, source_file="b", tasks=[
        task("1", date(2026, 8, 20), 100, actual=date(2026, 9, 2), dep="SW"),
        task("2", date(2026, 9, 1), dep="AA"), task("3", date(2026, 9, 1), dep="AA")])
    mp, mc = metrics.compute_metrics(prev), metrics.compute_metrics(cur)
    rows = metrics.overdue_trend(mp, mc)
    assert [(r.department, r.previous, r.current, r.arrow) for r in rows] == [("AA", 0, 2, "▲"), ("SW", 1, 0, "▼")]
    ch = metrics.task_changes(mp, mc)
    assert {t.uid for t in ch["newly_overdue"]} == {"2", "3"}
    assert {t.uid for t in ch["newly_closed"]} == {"1"}
    assert {t.uid for t in ch["added"]} == {"3"}
