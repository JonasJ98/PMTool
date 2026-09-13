"""Synthetischer sechswöchiger Projektverlauf zum Testen ohne echte .mpp-Dateien.

Zwei Verwendungen:
  * ``generate_snapshots()``  – Snapshots direkt im Speicher (ohne Java)
  * ``write_demo_files(dir)`` – dieselben Stände als MSPDI-XML-Dateien (über MPXJ,
    Java nötig), inkl. Master-Datei mit eingefügter Unterdatei, um den kompletten
    Import-Pfad des Tools (Datei -> Reader -> Store) zu testen.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from .model import Snapshot, TaskRecord

DEPARTMENTS = ["AA", "AE-COS", "AE-ENG", "AE-QMM", "AE-TEF", "ENG", "ENG-EE",
               "ENG-ME", "EXT", "PUR", "QMM", "SW", "TEST"]
SUBPROJECT_DEPARTMENTS = {"SW", "TEST"}     # liegen in der Unterdatei

PROJECT_START = date(2022, 3, 7)            # Montag
SNAPSHOT_DAY = 4                            # Freitag (0 = Montag)


def _weekly_dates(weeks: int, start: date = PROJECT_START) -> list[date]:
    first_friday = start + timedelta(days=(SNAPSHOT_DAY - start.weekday()) % 7)
    return [first_friday + timedelta(weeks=i) for i in range(weeks)]


def _base_plan(seed: int = 42, n_tasks: int = 90) -> list[dict]:
    rnd = random.Random(seed)
    plan = []
    for i in range(1, n_tasks + 1):
        dep = rnd.choice(DEPARTMENTS)
        start = PROJECT_START + timedelta(days=rnd.randint(0, 40))
        dur = rnd.randint(3, 21)
        finish = start + timedelta(days=dur)
        plan.append({
            "uid": i, "name": f"{dep} Aufgabe {i:03d}", "department": dep,
            "start": start, "baseline_finish": finish,
            # Neigung zur Verzögerung je Aufgabe (Tage)
            "slip": max(0, int(rnd.gauss(2, 6))),
            # Wahrscheinlichkeit, rechtzeitig fertig zu werden
            "diligence": rnd.random(),
            "milestone": rnd.random() < 0.05,
        })
    return plan


def generate_snapshots(weeks: int = 6, seed: int = 42) -> list[Snapshot]:
    """Erzeugt Snapshots, in denen sich der Plan von Woche zu Woche verändert."""
    rnd = random.Random(seed + 1)
    plan = _base_plan(seed)
    snaps: list[Snapshot] = []
    dates = _weekly_dates(weeks)
    actual_finish: dict[int, date] = {}
    hold_uids: set[int] = set()
    for wi, as_of in enumerate(dates):
        tasks: list[TaskRecord] = []
        # Woche 3: zwei Aufgaben auf Hold, Woche 5: neue Aufgaben kommen dazu
        if wi == 2:
            hold_uids = {plan[5]["uid"], plan[17]["uid"]}
        extra = []
        if wi >= 4:
            for j in range(1, 6):
                uid = 900 + j
                dep = rnd.choice(DEPARTMENTS)
                extra.append({"uid": uid, "name": f"{dep} Nachtrag {j}", "department": dep,
                              "start": as_of - timedelta(days=3),
                              "baseline_finish": as_of + timedelta(days=rnd.randint(2, 20)),
                              "slip": 0, "diligence": 0.5, "milestone": False})
        for p in plan + extra:
            uid = p["uid"]
            current_finish = p["baseline_finish"] + timedelta(days=p["slip"])
            done = uid in actual_finish
            if not done and uid not in hold_uids:
                # Aufgabe wird geschlossen, wenn ihr Ende erreicht ist (mit Fleiß) oder
                # mit gewisser Wahrscheinlichkeit verspätet nachgeholt wird
                if current_finish <= as_of and rnd.random() < 0.55 + 0.4 * p["diligence"]:
                    actual_finish[uid] = min(as_of, max(current_finish, as_of - timedelta(days=rnd.randint(0, 6))))
                    done = True
                elif p["baseline_finish"] < as_of - timedelta(days=14) and rnd.random() < 0.5:
                    actual_finish[uid] = as_of - timedelta(days=rnd.randint(0, 4))
                    done = True
            pct = 100.0 if done else min(95.0, max(0.0, 100.0 * (as_of - p["start"]).days / max(1, (current_finish - p["start"]).days)))
            if p["start"] > as_of:
                pct = 0.0
            tasks.append(TaskRecord(
                uid=str(uid), name=p["name"], department=p["department"],
                start=p["start"], finish=actual_finish.get(uid, current_finish),
                baseline_finish=p["baseline_finish"], actual_finish=actual_finish.get(uid),
                percent_complete=pct, is_milestone=p["milestone"],
                is_active=uid not in hold_uids,
                source_file="Sub_SW_TEST.xml" if p["department"] in SUBPROJECT_DEPARTMENTS else "Master_Demo.xml",
            ))
        # Sammelvorgang je Abteilung (wird in Kennzahlen herausgefiltert)
        for dep in DEPARTMENTS:
            tasks.append(TaskRecord(uid=f"S-{dep}", name=f"Sammelvorgang {dep}", department=dep,
                                    start=PROJECT_START, finish=as_of, baseline_finish=None,
                                    actual_finish=None, percent_complete=0, is_summary=True))
        kw = as_of.isocalendar()[1]
        snaps.append(Snapshot(snapshot_date=as_of, source_file=f"Master_Demo_KW{kw:02d}.xml",
                              tasks=tasks, label="Demo"))
    return snaps


# --------------------------------------------------------------------------
# MSPDI-Dateien über MPXJ schreiben (für Import-Tests mit echter Dateikette)
# --------------------------------------------------------------------------
def write_demo_files(out_dir: str | Path, weeks: int = 6, seed: int = 42) -> list[Path]:
    from . import config
    from .reader import _ensure_jvm, _mpxj_class

    _ensure_jvm()
    import jpype
    LocalDateTime = jpype.JClass("java.time.LocalDateTime")
    ProjectFile = _mpxj_class("ProjectFile")
    Writer = _mpxj_class("writer.UniversalProjectWriter")
    FileFormat = _mpxj_class("writer.FileFormat")

    def ldt(d: date | None, hour: int):
        return None if d is None else LocalDateTime.of(d.year, d.month, d.day, hour, 0)

    def add(pf, t: TaskRecord):
        jt = pf.addTask()
        jt.setName(t.name)
        jt.setText(config.DEPARTMENT_TEXT_FIELD_INDEX, t.department)
        jt.setStart(ldt(t.start, 8))
        jt.setFinish(ldt(t.finish, 17))
        if t.baseline_finish:
            jt.setBaselineFinish(ldt(t.baseline_finish, 17))
        if t.actual_finish:
            jt.setActualFinish(ldt(t.actual_finish, 17))
        jt.setPercentageComplete(jpype.JDouble(t.percent_complete))
        jt.setMilestone(t.is_milestone)
        jt.setActive(t.is_active)
        return jt

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for snap in generate_snapshots(weeks, seed):
        kw = snap.snapshot_date.isocalendar()[1]
        master = ProjectFile()
        sub = ProjectFile()
        for pf in (master, sub):
            pf.getProjectProperties().setStatusDate(ldt(snap.snapshot_date, 17))
        for t in snap.tasks:
            if t.is_summary:
                continue
            add(sub if t.department in SUBPROJECT_DEPARTMENTS else master, t)
        # Platzhalter für die eingefügte Unterdatei mit "fremdem" Netzlaufwerk-Pfad
        ph = master.addTask()
        ph.setName("Sub_SW_TEST")
        ph.setSubprojectFile(f"\\\\fileserver\\projekte\\Sub_SW_TEST_KW{kw:02d}.xml")
        sub_path = out / f"Sub_SW_TEST_KW{kw:02d}.xml"
        master_path = out / f"Master_Demo_KW{kw:02d}.xml"
        Writer(FileFormat.MSPDI).write(sub, str(sub_path))
        Writer(FileFormat.MSPDI).write(master, str(master_path))
        written.append(master_path)
    return written
