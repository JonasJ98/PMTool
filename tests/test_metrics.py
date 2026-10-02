from datetime import date

from mpptool import metrics
from mpptool.model import Snapshot, TaskRecord, TaskStatus

AS_OF = date(2026, 9, 4)


def task(uid, finish, pct=0.0, baseline=None, actual=None, active=True, summary=False, dep="AA", cancel=False):
    return TaskRecord(uid=uid, name=f"T{uid}", department=dep, start=date(2026, 8, 1), finish=finish,
                      baseline_finish=baseline, actual_finish=actual, percent_complete=pct,
                      is_active=active, is_summary=summary, cancel_flag=cancel)


def test_status_classification():
    assert metrics.classify(task("1", date(2026, 9, 10)), AS_OF) == TaskStatus.OPEN
    assert metrics.classify(task("2", date(2026, 9, 1)), AS_OF) == TaskStatus.OPEN_OVERDUE
    assert metrics.classify(task("3", date(2026, 9, 1), 100, actual=date(2026, 9, 1)), AS_OF) == TaskStatus.CLOSED
    assert metrics.classify(task("4", date(2026, 9, 3), 100, baseline=date(2026, 9, 1), actual=date(2026, 9, 3)), AS_OF) == TaskStatus.CLOSED_OVERDUE
    assert metrics.classify(task("5", date(2026, 9, 1), active=False), AS_OF) == TaskStatus.HOLD
    assert metrics.classify(task("6", date(2026, 9, 1), cancel=True), AS_OF) == TaskStatus.CANCELLED


def test_metrics_counts_and_summary_filter():
    snap = Snapshot(snapshot_date=AS_OF, source_file="x.mpp", tasks=[
        task("1", date(2026, 9, 10)),
        task("2", date(2026, 9, 1), dep="SW"),
        task("3", date(2026, 9, 1), 100, actual=date(2026, 9, 1)),
        task("4", date(2026, 9, 1), summary=True),
        task("5", date(2026, 9, 1), active=False),
        task("6", date(2026, 9, 1), cancel=True),
    ])
    m = metrics.compute_metrics(snap)
    assert m.monitored == 5
    assert m.planned_closed == 2          # #2 und #3 (Hold/Cancelled zählen nicht)
    assert m.actually_closed == 1
    assert m.open_overdue == 1
    assert m.hold == 1
    assert m.cancelled == 1
    assert m.tasks_count == 5             # alle mit Start < Ende (>0 Tage Dauer)
    assert m.milestones_count == 0
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
    rows = metrics.overdue_trend([mp, mc])
    assert [(r.department, r.previous, r.current, r.arrow) for r in rows] == [("AA", 0, 2, "▲"), ("SW", 1, 0, "▼")]
    assert [r.history for r in rows] == [[0, 2], [1, 0]]
    ch = metrics.task_changes(mp, mc)
    assert {t.uid for t in ch["newly_overdue"]} == {"2", "3"}
    assert {t.uid for t in ch["newly_closed"]} == {"1"}
    assert {t.uid for t in ch["added"]} == {"3"}


def test_zero_duration_non_milestones_not_counted():
    d = date(2026, 9, 1)
    rec = lambda uid, **kw: TaskRecord(uid=uid, name=uid, department="AA", start=kw.pop("start", d), finish=d,
                                       baseline_finish=None, actual_finish=None, percent_complete=0, **kw)
    snap = Snapshot(snapshot_date=AS_OF, source_file="x.mpp", tasks=[
        rec("task", start=date(2026, 8, 20)),           # Dauer > 0 (Datum)      -> Aufgabe
        rec("one-day", duration=1.0),                   # 1-Tages-Aufgabe (MS-Project-Dauer) -> Aufgabe
        rec("ms", is_milestone=True),                   # Meilenstein            -> Meilenstein
        rec("sammel"),                                  # 0 Tage, kein Meilenstein -> nicht gezählt
        rec("sammel-native", start=date(2026, 8, 20), duration=0.0),  # MS-Project-Dauer 0 -> nicht gezählt
    ])
    m = metrics.compute_metrics(snap)
    assert set(m.statuses) == {"task", "one-day", "ms"}
    assert (m.monitored, m.tasks_count, m.milestones_count) == (3, 2, 1)


def test_overdue_trend_department_filter():
    s = Snapshot(snapshot_date=AS_OF, source_file="a", tasks=[
        task("1", date(2026, 9, 1), dep="AA"), task("2", date(2026, 9, 1), dep="SW"),
        task("3", date(2026, 9, 1), dep="SW")])
    m = metrics.compute_metrics(s)
    assert [r.department for r in metrics.overdue_trend([m], departments={"AA"})] == ["AA"]
    assert {t.uid for t in metrics.overdue_tasks(m, {"SW"})} == {"2", "3"}
    assert metrics.all_departments([s]) == ["AA", "SW"]


def test_finish_trend():
    s1 = Snapshot(snapshot_date=date(2026, 8, 28), source_file="a", tasks=[
        task("1", date(2026, 10, 1), baseline=date(2026, 10, 1)), task("2", date(2026, 9, 1))])
    s2 = Snapshot(snapshot_date=AS_OF, source_file="b", tasks=[
        task("1", date(2026, 10, 15), baseline=date(2026, 10, 1)),
        task("9", date(2027, 1, 1), summary=True)])          # Sammelvorgang zählt nicht
    pts = metrics.finish_trend([metrics.compute_metrics(s2), metrics.compute_metrics(s1)])
    assert [p.expected_finish for p in pts] == [date(2026, 10, 1), date(2026, 10, 15)]
    assert pts[-1].slip_vs_baseline == 14
