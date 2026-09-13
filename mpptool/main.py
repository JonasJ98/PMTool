"""Kommandozeile des MPP-Auswertungstools.

Beispiele:
  python -m mpptool.main demo                      # 6 synthetische Wochen importieren
  python -m mpptool.main demo-files ./demo          # Demo als MSPDI-XML-Dateien schreiben
  python -m mpptool.main import Plan.mpp --date 2026-09-04 --label "KW36"
  python -m mpptool.main list
  python -m mpptool.main report --out output/review.pptx        # alle Snapshots
  python -m mpptool.main report --ids 3 4 --out output/review.pdf
  python -m mpptool.main gui
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from . import config, demo_data, report
from .snapshot_store import SnapshotStore


def _store(args) -> SnapshotStore:
    return SnapshotStore(args.db)


def cmd_import(args) -> int:
    from .reader import read_snapshot
    snap_date = date.fromisoformat(args.date) if args.date else None
    snap, warnings = read_snapshot(args.file, snap_date, args.label or "")
    for w in warnings:
        print("WARNUNG:", w)
    with _store(args) as store:
        sid = store.add_snapshot(snap)
    print(f"Snapshot #{sid} importiert: {snap.display_name}, {len(snap.tasks)} Aufgaben")
    return 0


def cmd_demo(args) -> int:
    with _store(args) as store:
        for s in demo_data.generate_snapshots(args.weeks):
            sid = store.add_snapshot(s)
            print(f"Snapshot #{sid}: {s.display_name} ({len(s.tasks)} Aufgaben)")
    return 0


def cmd_demo_files(args) -> int:
    files = demo_data.write_demo_files(args.dir, args.weeks)
    for f in files:
        print(f)
    print("Import z. B.:  python -m mpptool.main import", files[-1])
    return 0


def cmd_list(args) -> int:
    with _store(args) as store:
        snaps = store.list_snapshots()
    if not snaps:
        print("Keine Snapshots vorhanden.")
    for s in snaps:
        print(f"#{s.snapshot_id:<4} {s.display_name:<32} {s.source_file:<30} importiert {s.imported_at}")
    return 0


def cmd_delete(args) -> int:
    with _store(args) as store:
        for i in args.ids:
            store.delete_snapshot(i)
            print(f"Snapshot #{i} gelöscht")
    return 0


def cmd_report(args) -> int:
    with _store(args) as store:
        ids = args.ids or [s.snapshot_id for s in store.list_snapshots()]
        if not ids:
            print("Keine Snapshots vorhanden – zuerst importieren oder `demo` ausführen.")
            return 1
        snaps = store.load_snapshots(ids)
    report_date = date.fromisoformat(args.report_date) if args.report_date else None
    rv = report.build_review(snaps, args.name, report_date=report_date)
    out = Path(args.out) if args.out else config.OUTPUT_DIR / f"review_{rv.cur_label}.pptx"
    if out.suffix.lower() == ".pdf":
        report.export_pdf(rv, out)
    else:
        report.export_pptx(rv, out)
    m = rv.current
    print(f"Bericht geschrieben: {out}")
    print(f"  {rv.cur_label}: {m.monitored} Aufgaben, {m.actually_closed}/{m.planned_closed} geschlossen "
          f"({m.fulfilment_pct:.1f} %), {m.open_overdue} überfällig, {m.hold} Hold")
    return 0


def cmd_gui(args) -> int:
    from .gui.app import run
    return run(db_path=args.db)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mpptool", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=None, help=f"SQLite-Datei (Standard: {config.DB_PATH})")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("import", help="MS-Project-Datei als Snapshot importieren")
    s.add_argument("file")
    s.add_argument("--date", help="Stichtag YYYY-MM-DD (Standard: Statusdatum der Datei bzw. Dateidatum)")
    s.add_argument("--label", help="Bezeichnung des Snapshots")
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("demo", help="synthetische Wochen-Snapshots importieren")
    s.add_argument("--weeks", type=int, default=6)
    s.set_defaults(func=cmd_demo)

    s = sub.add_parser("demo-files", help="Demo-Stände als MSPDI-XML-Dateien schreiben (Java nötig)")
    s.add_argument("dir")
    s.add_argument("--weeks", type=int, default=6)
    s.set_defaults(func=cmd_demo_files)

    s = sub.add_parser("list", help="gespeicherte Snapshots anzeigen")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("delete", help="Snapshots löschen")
    s.add_argument("ids", type=int, nargs="+")
    s.set_defaults(func=cmd_delete)

    s = sub.add_parser("report", help="Bericht als PPTX oder PDF erzeugen")
    s.add_argument("--ids", type=int, nargs="*", help="Snapshot-IDs (Standard: alle)")
    s.add_argument("--out", help="Zieldatei .pptx oder .pdf")
    s.add_argument("--name", help="Projektname für den Bericht")
    s.add_argument("--report-date", help="Auswertungstag/Stichtag YYYY-MM-DD (Standard: heute)")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("gui", help="Desktop-Oberfläche starten")
    s.set_defaults(func=cmd_gui)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
