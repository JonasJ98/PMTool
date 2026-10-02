"""Reader-Logik ohne JVM: Fake-Projektobjekte mit derselben Getter-Schnittstelle."""
from datetime import date
from pathlib import Path

import pytest

from mpptool import config, reader


class FakeTask:
    def __init__(self, uid, name, text1="", finish=None, subproject=None, summary=False, pct=0):
        self._uid, self._name, self._text1, self._finish = uid, name, text1, finish
        self._sub, self._summary, self._pct = subproject, summary, pct

    def getUniqueID(self): return self._uid
    def getName(self): return self._name
    def getText(self, i): return self._text1 if i == 1 else None
    def getStart(self): return date(2026, 8, 1)
    def getFinish(self): return self._finish
    def getBaselineFinish(self): return None
    def getActualFinish(self): return None
    def getPercentageComplete(self): return self._pct
    def getSummary(self): return self._summary
    def getMilestone(self): return False
    def getActive(self): return True
    def getExternalTask(self): return False
    def getOutlineLevel(self): return 1
    def getSubprojectFile(self): return self._sub
    def getResourceGroup(self): return None
    def getResourceAssignments(self): return []


class FakeProject:
    def __init__(self, tasks): self._tasks = tasks
    def getTasks(self): return self._tasks


def test_resolve_subproject_path(tmp_path):
    (tmp_path / "Sub_SW.mpp").write_bytes(b"x")
    nested = tmp_path / "teilprojekte"
    nested.mkdir()
    (nested / "Sub_HW.mpp").write_bytes(b"x")
    assert reader.resolve_subproject_path(r"\\server\share\Sub_SW.mpp", tmp_path) == tmp_path / "Sub_SW.mpp"
    assert reader.resolve_subproject_path(r"P:\alt\Sub_HW.mpp", tmp_path) == nested / "Sub_HW.mpp"
    assert reader.resolve_subproject_path(r"P:\alt\Fehlt.mpp", tmp_path) is None


def test_extract_records_expands_subprojects(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DEPARTMENT_TEXT_FIELD_INDEX", 1)
    sub_file = tmp_path / "Sub_SW.mpp"
    sub_file.write_bytes(b"x")
    master = FakeProject([
        FakeTask(1, "Master A", "AA", date(2026, 9, 1)),
        FakeTask(2, "Sub_SW", subproject=r"\\server\Sub_SW.mpp"),
        FakeTask(3, "Fehlend", subproject=r"\\server\Fehlt.mpp"),
    ])
    sub = FakeProject([FakeTask(1, "SW 1", "SW", date(2026, 9, 2)), FakeTask(2, "SW 2", "SW", date(2026, 9, 3))])
    loader_calls = []

    def loader(p: Path):
        loader_calls.append(p)
        return sub

    warnings = []
    recs = reader.extract_records(master, "Master.mpp", master_dir=tmp_path, project_loader=loader, warnings=warnings)
    assert loader_calls == [sub_file]
    assert [r.uid for r in recs] == ["1", "Sub_SW/1", "Sub_SW/2", "3"]
    assert recs[1].source_file == "Sub_SW.mpp" and recs[1].department == "SW"
    assert len(warnings) == 1 and "Fehlt.mpp" in warnings[0]


@pytest.mark.skipif(not pytest.importorskip("jpype"), reason="JPype fehlt")
def test_mspdi_roundtrip_via_mpxj(tmp_path):
    """Kompletter Dateipfad über MPXJ (benötigt Java)."""
    from mpptool import demo_data, metrics
    try:
        files = demo_data.write_demo_files(tmp_path, weeks=2)
    except RuntimeError as exc:
        pytest.skip(str(exc))
    snap, warnings = reader.read_snapshot(files[-1])
    assert warnings == []
    mem = metrics.compute_metrics(demo_data.generate_snapshots(weeks=2)[-1])
    got = metrics.compute_metrics(snap)
    assert got.monitored == mem.monitored
    assert got.open_overdue == mem.open_overdue
    assert got.actually_closed == mem.actually_closed
    assert any(t.source_file.startswith("Sub_SW_TEST") for t in snap.tasks)


def test_date_from_filename():
    assert reader.date_from_filename("2022_11_24_CCC.mpp") == date(2022, 11, 24)
    assert reader.date_from_filename("Plan-2023-01-05.mpp") == date(2023, 1, 5)
    assert reader.date_from_filename("CCC_20221202.mpp") == date(2022, 12, 2)
    assert reader.date_from_filename("Stand 24.11.2022.mpp") == date(2022, 11, 24)
    assert reader.date_from_filename("Master_Demo_KW11.xml") is None
    assert reader.date_from_filename("2022_13_45.mpp") is None


def test_suggest_snapshot_date(tmp_path):
    class Props:
        def getStatusDate(self): return date(2022, 3, 18)
        def getCurrentDate(self): return date(2026, 10, 2)

    class Proj:
        def getProjectProperties(self): return Props()

    f = tmp_path / "2022_11_24_CCC.mpp"
    f.write_bytes(b"x")
    assert reader.suggest_snapshot_date(f, Proj()) == (date(2022, 11, 24), "aus Dateiname")
    g = tmp_path / "CCC.mpp"
    g.write_bytes(b"x")
    assert reader.suggest_snapshot_date(g, Proj()) == (date(2022, 3, 18), "Statusdatum der Datei")
    assert reader.suggest_snapshot_date(g)[1] == "Änderungsdatum der Datei"
