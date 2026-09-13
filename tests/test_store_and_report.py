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
    assert len(Presentation(str(pptx)).slides) == 8
