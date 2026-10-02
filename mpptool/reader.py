"""Einlesen von MS-Project-Dateien (.mpp, .xml/MSPDI, .mpx) über MPXJ.

MPXJ ist eine Java-Bibliothek; der Zugriff aus Python erfolgt über JPype.
Die JVM wird beim ersten Lesevorgang gestartet (Java-Laufzeit erforderlich).

Unterdateien (eingefügte Teilprojekte):
    MPXJ liefert für eine eingefügte Unterdatei eine Platzhalter-Aufgabe mit
    gesetztem ``SubprojectFile``. Da die gespeicherten Pfade in der Regel auf
    Netzlaufwerke des Ursprungsrechners zeigen, wird die Datei über eine eigene
    Suche (Verzeichnis der Master-Datei + ``config.SUBPROJECT_SEARCH_DIRS``)
    aufgelöst und rekursiv eingelesen. Die Aufgaben der Unterdatei ersetzen die
    Platzhalter-Aufgabe.

Die Extraktion (``extract_records``) arbeitet gegen eine schmale Getter-
Schnittstelle, sodass sie in Tests ohne JVM mit Fake-Objekten prüfbar ist.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from . import config
from .model import Snapshot, TaskRecord

log = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".mpp", ".xml", ".mpx", ".mpt", ".mspdi"}

_jvm_started = False


# --------------------------------------------------------------------------
# JVM / MPXJ
# --------------------------------------------------------------------------
def _ensure_jvm() -> None:
    global _jvm_started
    if _jvm_started:
        return
    try:
        import jpype
        import jpype.imports  # noqa: F401
        import mpxj  # noqa: F401  – registriert die MPXJ-Jars im Klassenpfad
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "MPXJ/JPype sind nicht installiert (pip install mpxj JPype1)."
        ) from exc
    if not jpype.isJVMStarted():
        jvm = _bundled_jvm_path()
        try:
            if jvm:
                jpype.startJVM(str(jvm), classpath=jpype.getClassPath())
            else:
                jpype.startJVM(classpath=jpype.getClassPath())
        except Exception as exc:  # pragma: no cover
            raise RuntimeError(
                "Java-Laufzeitumgebung konnte nicht gestartet werden. "
                "Entweder ein JDK/JRE installieren (JAVA_HOME setzen) oder eine portable JRE "
                "im Ordner 'jre' neben der Anwendung ablegen (siehe build.ps1)."
            ) from exc
    _jvm_started = True


def _bundled_jvm_path() -> Path | None:
    """Portable JRE neben der .exe (PyInstaller) bzw. im Projektordner finden.

    Erwartete Struktur:  <app>/jre/bin/server/jvm.dll  (Windows)
                         <app>/jre/lib/server/libjvm.so (Linux)
    """
    import sys
    roots = []
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).parent)
    roots.append(config.BASE_DIR)
    env = os.environ.get("MPPTOOL_JRE")
    if env:
        roots.insert(0, Path(env).parent)
    for root in roots:
        for jre in (root / "jre", Path(env) if env else None):
            if jre is None:
                continue
            for rel in ("bin/server/jvm.dll", "bin/client/jvm.dll", "lib/server/libjvm.so", "lib/server/libjvm.dylib"):
                cand = jre / rel
                if cand.is_file():
                    log.info("Verwende portable JRE: %s", cand)
                    return cand
    return None


def _mpxj_class(name: str):
    """Klasse aus MPXJ laden – unterstützt Paketname org.mpxj (>=14) und net.sf.mpxj (<14)."""
    import jpype
    for pkg in ("org.mpxj", "net.sf.mpxj"):
        try:
            return jpype.JClass(f"{pkg}.{name}")
        except Exception:
            continue
    raise RuntimeError(f"MPXJ-Klasse {name} nicht gefunden")


def read_project_file(path: str | os.PathLike):
    """Rohes MPXJ-ProjectFile-Objekt einlesen."""
    _ensure_jvm()
    reader = _mpxj_class("reader.UniversalProjectReader")()
    project = reader.read(str(path))
    if project is None:
        raise ValueError(f"Datei konnte nicht als MS-Project-Datei gelesen werden: {path}")
    return project


# --------------------------------------------------------------------------
# Konvertierung Java -> Python
# --------------------------------------------------------------------------
def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    # java.time.LocalDateTime / LocalDate
    if hasattr(value, "toLocalDate"):
        value = value.toLocalDate()
    if hasattr(value, "getYear"):
        return date(int(value.getYear()), int(value.getMonthValue()), int(value.getDayOfMonth()))
    return None


def _to_float(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value.doubleValue()) if hasattr(value, "doubleValue") else float(value)
    except Exception:
        return 0.0


def _to_str(value: Any) -> str:
    return "" if value is None else str(value)


def _to_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    try:
        return bool(value.booleanValue()) if hasattr(value, "booleanValue") else bool(value)
    except Exception:
        return default


def _department_of(task: Any) -> str:
    text = _to_str(task.getText(config.DEPARTMENT_TEXT_FIELD_INDEX)).strip()
    if text:
        return text
    if config.DEPARTMENT_FALLBACK_TO_RESOURCE_GROUP:
        grp = _to_str(getattr(task, "getResourceGroup", lambda: None)()).strip()
        if grp:
            return grp.split(",")[0].strip()
        try:
            for a in task.getResourceAssignments():
                r = a.getResource()
                if r is not None and r.getGroup():
                    return _to_str(r.getGroup()).strip()
        except Exception:
            pass
    return ""


def _duration_days_of(task: Any) -> float | None:
    """MS-Project-Feld "Dauer" in Tagen (Arbeitstage laut Projektkalender).
    None, falls nicht ermittelbar – dann greift der Datums-Fallback."""
    try:
        dur = task.getDuration()
    except Exception:
        return None
    if dur is None:
        return None
    try:
        props = task.getParentFile().getProjectProperties()
        dur = dur.convertUnits(_mpxj_class("TimeUnit").DAYS, props)
    except Exception:
        pass  # Einheit unverändert lassen – für "Dauer > 0" genügt das Vorzeichen
    try:
        return float(dur.getDuration())
    except Exception:
        return None


def _hold_flag_of(task: Any) -> bool:
    if config.HOLD_TEXT_FIELD_INDEX is None:
        return False
    val = _to_str(task.getText(config.HOLD_TEXT_FIELD_INDEX)).strip().lower()
    return val in config.HOLD_TEXT_VALUES


def _cancel_flag_of(task: Any) -> bool:
    if config.CANCEL_TEXT_FIELD_INDEX is None:
        return False
    val = _to_str(task.getText(config.CANCEL_TEXT_FIELD_INDEX)).strip().lower()
    return val in config.CANCEL_TEXT_VALUES


def task_to_record(task: Any, source_file: str, uid_prefix: str = "") -> TaskRecord:
    uid = f"{uid_prefix}{_to_str(task.getUniqueID())}"
    return TaskRecord(
        uid=uid,
        name=_to_str(task.getName()),
        department=_department_of(task),
        start=_to_date(task.getStart()),
        finish=_to_date(task.getFinish()),
        baseline_finish=_to_date(task.getBaselineFinish()),
        actual_finish=_to_date(task.getActualFinish()),
        percent_complete=_to_float(task.getPercentageComplete()),
        is_summary=_to_bool(task.getSummary(), False),
        is_milestone=_to_bool(task.getMilestone(), False),
        is_active=_to_bool(task.getActive(), True),
        is_external=_to_bool(task.getExternalTask(), False),
        source_file=source_file,
        outline_level=int(_to_float(task.getOutlineLevel()) or 1),
        hold_flag=_hold_flag_of(task),
        cancel_flag=_cancel_flag_of(task),
        duration=_duration_days_of(task),
    )


# --------------------------------------------------------------------------
# Unterdatei-Auflösung
# --------------------------------------------------------------------------
def resolve_subproject_path(stored_path: str, master_dir: Path,
                            search_dirs: Iterable[Path] = ()) -> Path | None:
    """Gespeicherten (oft fremden Windows-/Netzlaufwerk-)Pfad auf lokale Datei abbilden."""
    if not stored_path:
        return None
    raw = stored_path.replace("\\", "/")
    # MS Project speichert teils "pfad\datei.mpp\" oder mit Verweis-Suffix
    raw = raw.rstrip("/")
    candidates: list[Path] = []
    direct = Path(raw)
    if direct.is_absolute():
        candidates.append(direct)
    # nicht Path(raw).name: "//server/datei.mpp" gilt unter Windows als UNC-Wurzel ohne Namen
    basename = raw.split("/")[-1]
    dirs = [master_dir, *search_dirs]
    for d in dirs:
        candidates.append(Path(d) / basename)
        candidates.append(Path(d) / raw)  # relativer Pfad relativ zum Master
    for c in candidates:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    # letzte Stufe: rekursive Suche nach Dateinamen in den Suchverzeichnissen
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for found in d.rglob(basename):
            if found.is_file():
                return found
    return None


def extract_records(project: Any, source_file: str, *,
                    master_dir: Path | None = None,
                    depth: int = 0,
                    uid_prefix: str = "",
                    project_loader: Callable[[Path], Any] | None = None,
                    warnings: list[str] | None = None) -> list[TaskRecord]:
    """Aufgaben eines (MPXJ-)Projektobjekts extrahieren, Unterdateien auflösen."""
    warnings = warnings if warnings is not None else []
    master_dir = master_dir or Path(".")
    records: list[TaskRecord] = []
    counter = 0
    for task in project.getTasks():
        if task is None or task.getName() is None and task.getUniqueID() is None:
            continue
        sub = _to_str(task.getSubprojectFile()).strip()
        if sub and config.EXPAND_SUBPROJECTS:
            if depth >= config.MAX_SUBPROJECT_DEPTH:
                warnings.append(f"Max. Unterdatei-Tiefe erreicht bei {sub}")
            else:
                resolved = resolve_subproject_path(sub, master_dir, config.SUBPROJECT_SEARCH_DIRS)
                if resolved is None:
                    warnings.append(f"Unterdatei nicht gefunden: {sub} (Platzhalter bleibt erhalten)")
                else:
                    counter += 1
                    loader = project_loader or read_project_file
                    try:
                        subproject = loader(resolved)
                    except Exception as exc:
                        warnings.append(f"Unterdatei {resolved.name} nicht lesbar: {exc}")
                        subproject = None
                    if subproject is not None:
                        prefix = f"{uid_prefix}{resolved.stem}/"
                        records.extend(extract_records(
                            subproject, resolved.name, master_dir=resolved.parent,
                            depth=depth + 1, uid_prefix=prefix,
                            project_loader=loader, warnings=warnings))
                        continue  # Platzhalter durch Unterdatei-Aufgaben ersetzt
        records.append(task_to_record(task, source_file, uid_prefix))
    # Zeile 0 (Projektsammelvorgang) ist bei MPXJ Sammelvorgang, wird über Filter entfernt
    return records


# --------------------------------------------------------------------------
# Öffentliche API
# --------------------------------------------------------------------------
def read_snapshot(path: str | os.PathLike, snapshot_date: date | None = None,
                  label: str = "") -> tuple[Snapshot, list[str]]:
    """Datei einlesen und als Snapshot zurückgeben (plus Warnungen)."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(p)
    if p.suffix.lower() not in SUPPORTED_SUFFIXES:
        log.warning("Unbekannte Dateiendung %s – Versuch über UniversalProjectReader", p.suffix)
    project = read_project_file(p)
    warnings: list[str] = []
    records = extract_records(project, p.name, master_dir=p.parent, warnings=warnings)

    source = "vorgegeben"
    if snapshot_date is None:
        snapshot_date, source = suggest_snapshot_date(p, project)

    snap = Snapshot(snapshot_date=snapshot_date, source_file=p.name, tasks=records, label=label,
                    date_source=source)
    return snap, warnings


# Datum im Dateinamen: 2022_11_24, 2022-11-24, 2022.11.24, 20221124 oder 24.11.2022
_NAME_DATE_PATTERNS = (
    (re.compile(r"(?<!\d)(20\d{2})[_\-. ]?(\d{2})[_\-. ]?(\d{2})(?!\d)"), (1, 2, 3)),
    (re.compile(r"(?<!\d)(\d{2})[_\-.](\d{2})[_\-.](20\d{2})(?!\d)"), (3, 2, 1)),
)


def date_from_filename(name: str) -> date | None:
    for rx, (yi, mi, di) in _NAME_DATE_PATTERNS:
        for m in rx.finditer(name):
            try:
                return date(int(m.group(yi)), int(m.group(mi)), int(m.group(di)))
            except ValueError:
                continue
    return None


def suggest_snapshot_date(path: Path, project: Any = None) -> tuple[date, str]:
    """Stichtag für den Import vorschlagen (im Dialog bestätigen oder ändern).

    Reihenfolge: Datum im Dateinamen -> Statusdatum der Datei -> Änderungsdatum
    der Datei. Das MS-Project-"Aktuelle Datum" wird bewusst nicht verwendet –
    es entspricht meist dem Tag, an dem die Datei zuletzt geöffnet wurde."""
    d = date_from_filename(path.name)
    if d:
        return d, "aus Dateiname"
    d = _status_date_of(project) if project is not None else None
    if d:
        return d, "Statusdatum der Datei"
    return date.fromtimestamp(path.stat().st_mtime), "Änderungsdatum der Datei"


def _status_date_of(project: Any) -> date | None:
    try:
        return _to_date(project.getProjectProperties().getStatusDate())
    except Exception:
        return None
