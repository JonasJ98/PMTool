"""Hilfsskript: Belegte Textfelder einer echten .mpp-Datei anzeigen.

Aufruf:  python -m mpptool.inspect_fields <datei.mpp>

Zeigt für Text1..Text30 die Anzahl belegter Aufgaben und Beispielwerte, damit
``config.DEPARTMENT_TEXT_FIELD_INDEX`` korrekt gesetzt werden kann. Zusätzlich
werden Ressourcengruppen und eingefügte Unterdateien aufgelistet.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict

from .reader import read_project_file


def inspect(path: str) -> None:
    project = read_project_file(path)
    tasks = [t for t in project.getTasks() if t is not None]
    print(f"Datei: {path}")
    print(f"Aufgaben: {len(tasks)}   Ressourcen: {len(list(project.getResources()))}")
    print()
    print("Belegte Textfelder (Text1..Text30):")
    for i in range(1, 31):
        vals = Counter()
        for t in tasks:
            v = t.getText(i)
            if v is not None and str(v).strip():
                vals[str(v).strip()] += 1
        if vals:
            examples = ", ".join(f"{k} ({n})" for k, n in vals.most_common(8))
            print(f"  Text{i:<3} {sum(vals.values()):4d} Aufgaben  ->  {examples}")
    print()
    groups = Counter()
    for r in project.getResources():
        if r is not None and r.getGroup():
            groups[str(r.getGroup())] += 1
    print("Ressourcengruppen:", ", ".join(f"{g} ({n})" for g, n in groups.most_common()) or "-")
    print()
    subs = defaultdict(int)
    for t in tasks:
        s = t.getSubprojectFile()
        if s:
            subs[str(s)] += 1
    print("Eingefügte Unterdateien:")
    for s in subs:
        print("  ", s)
    if not subs:
        print("   -")
    props = project.getProjectProperties()
    print()
    print("Statusdatum:", props.getStatusDate(), "  Aktuelles Datum:", props.getCurrentDate())


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(__doc__)
        return 1
    inspect(argv[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
