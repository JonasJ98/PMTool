"""Zentrale Stellschrauben des Tools.

Alle hier definierten Werte können in einer Folgesession angepasst werden,
sobald echte .mpp-Dateien vorliegen (siehe Übergabe, Abschnitt 5).
"""
from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------
# Speicherort
# --------------------------------------------------------------------------
import os as _os
import sys as _sys

if getattr(_sys, "frozen", False):
    # Gepackte Anwendung (PyInstaller): neben der .exe liegt ggf. der Ordner "jre";
    # Daten gehören in ein beschreibbares Nutzerverzeichnis.
    BASE_DIR = Path(_sys.executable).resolve().parent
    _user_dir = Path(_os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "mpptool"
    DATA_DIR = _user_dir / "data"
    OUTPUT_DIR = Path.home() / "Documents" / "mpptool"
else:
    BASE_DIR = Path(__file__).resolve().parent.parent
    DATA_DIR = BASE_DIR / "data"
    OUTPUT_DIR = BASE_DIR / "output"
DB_PATH = DATA_DIR / "snapshots.sqlite"

# --------------------------------------------------------------------------
# Fachabteilung
# --------------------------------------------------------------------------
# Nummer des MS-Project-Textfelds (Text1 .. Text30), in dem die Fachabteilung
# je Aufgabe gepflegt ist. PLATZHALTER – mit `python -m mpptool.inspect_fields
# <datei.mpp>` an einer echten Datei ermitteln und hier eintragen.
DEPARTMENT_TEXT_FIELD_INDEX = 1

# Fallback, wenn das Textfeld leer ist: Ressourcengruppe der ersten
# zugewiesenen Ressource verwenden (MS Project "Group"-Feld der Ressource).
DEPARTMENT_FALLBACK_TO_RESOURCE_GROUP = True

# Name für Aufgaben ohne erkennbare Abteilung.
DEPARTMENT_UNKNOWN = "n/a"

# Abbildung älterer Schreibweisen/Umbenennungen auf den kanonischen Namen.
# Beispiel: {"AE-ENG-2": "AE-ENG", "Purchasing": "PUR"}
DEPARTMENT_ALIASES: dict[str, str] = {}

# --------------------------------------------------------------------------
# Hold-Erkennung
# --------------------------------------------------------------------------
# True: eine inaktive Aufgabe (MS Project "Active" = Nein) gilt als Hold.
USE_NATIVE_ACTIVE_FLAG_FOR_HOLD = True
# Optional zusätzlich: Textfeld, das bei Wert "Hold"/"On Hold" die Aufgabe
# als pausiert markiert. None = nicht verwenden.
HOLD_TEXT_FIELD_INDEX: int | None = None
HOLD_TEXT_VALUES = {"hold", "on hold", "pausiert"}

# --------------------------------------------------------------------------
# Unterdateien (eingefügte Teilprojekte)
# --------------------------------------------------------------------------
EXPAND_SUBPROJECTS = True
# Verzeichnisse, in denen nach den Unterdateien gesucht wird, falls der in
# der Master-Datei gespeicherte Pfad auf dem Rechner nicht existiert.
# Das Verzeichnis der Master-Datei wird immer zusätzlich durchsucht.
SUBPROJECT_SEARCH_DIRS: list[Path] = []
MAX_SUBPROJECT_DEPTH = 3

# --------------------------------------------------------------------------
# Kennzahlen
# --------------------------------------------------------------------------
EXCLUDE_SUMMARY_TASKS = True
EXCLUDE_MILESTONES = False
# Platzhalter-Zeilen für externe Aufgaben (MS Project "External Task")
EXCLUDE_EXTERNAL_PLACEHOLDERS = True

# Anzahl der Abteilungen in der "Top-Overdues"-Vergleichstabelle
TOP_N_OVERDUES = 5

# --------------------------------------------------------------------------
# Bericht
# --------------------------------------------------------------------------
REPORT_TITLE = "PJM Project Review"
REPORT_AUTHOR = "J.A. Project Engineering"
