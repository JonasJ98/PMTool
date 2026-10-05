from mpptool import demo_data, report
from mpptool.snapshot_store import SnapshotStore


def test_store_roundtrip(tmp_path):
    snaps = demo_data.generate_snapshots(weeks=3)
    with SnapshotStore(tmp_path / "t.sqlite") as store:
        ids = [store.add_snapshot(s) for s in snaps]
        assert [s.snapshot_id for s in store.list_snapshots()] == ids
        loaded = store.load_snapshot(ids[-1])
        assert loaded.snapshot_date == snaps[-1].snapshot_date
        assert len(loaded.tasks) == len(snaps[-1].tasks)
        assert {t.uid for t in loaded.tasks} == {t.uid for t in snaps[-1].tasks}
        store.delete_snapshot(ids[0])
        assert len(store.list_snapshots()) == 2


def test_review_and_exports(tmp_path):
    rv = report.build_review(demo_data.generate_snapshots(weeks=4), "Test")
    assert len(rv.timeline) == 4
    assert rv.previous is not None
    pptx = report.export_pptx(rv, tmp_path / "r.pptx")
    pdf = report.export_pdf(rv, tmp_path / "r.pdf")
    assert pptx.stat().st_size > 10_000
    assert pdf.stat().st_size > 10_000
    from pptx import Presentation
    assert len(Presentation(str(pptx)).slides) == 9


def test_store_keeps_native_duration(tmp_path):
    snap = demo_data.generate_snapshots(weeks=1)[0]
    snap.tasks[0].duration = 0.0
    snap.tasks[1].duration = 2.5
    snap.tasks[1].wbs = "1.2.3"
    with SnapshotStore(tmp_path / "t.sqlite") as store:
        loaded = store.load_snapshot(store.add_snapshot(snap))
    by_uid = {t.uid: t.duration for t in loaded.tasks}
    assert by_uid[snap.tasks[0].uid] == 0.0
    assert by_uid[snap.tasks[1].uid] == 2.5
    assert by_uid[snap.tasks[2].uid] is None
    assert {t.uid: t.wbs for t in loaded.tasks}[snap.tasks[1].uid] == "1.2.3"


def test_review_group_selection(tmp_path):
    snaps = demo_data.generate_snapshots(weeks=3)
    full = report.build_review(snaps, "Test")
    groups = full.all_departments[:2]
    rv = report.build_review(snaps, "Test", departments=groups)
    assert all(r.department in groups for r in rv.trend_rows)
    assert all(t.department in groups for t in rv.overdue_list)
    assert rv.group_suffix == f" (Auswahl: 2 von {len(full.all_departments)} Gruppen)"
    assert full.group_suffix == ""
    # Übersicht/Timeline bleiben Gesamtprojekt
    assert rv.current.monitored == full.current.monitored
    fig = report.figure_department_status(rv)
    assert [t.get_text() for t in fig.axes[0].get_xticklabels()] == sorted(groups)
    assert report.export_pptx(rv, tmp_path / "r.pptx").stat().st_size > 10_000


def test_review_header_and_week_range():
    from datetime import date
    snaps = demo_data.generate_snapshots(weeks=3)
    rv = report.build_review(snaps, "Test/Projekt", report_date=snaps[-1].snapshot_date,
                             week_from=date(2022, 3, 1), week_to=date(2022, 3, 31))
    assert rv.header.startswith("Projekt: Test/Projekt  ·  Timeline: Master_Demo_KW")
    assert "Auswertungsdatum: " in rv.header and "(KW" in rv.header
    assert rv.default_filename("pdf").startswith("Test_Projekt_Review_KW") and rv.default_filename("pdf").endswith(".pdf")
    assert [p.label for p in rv.week_points][0] == "KW09" and len(rv.week_points) == 5
    assert sum(p.is_evaluation_week for p in rv.week_points) == 1
