"""Hauptfenster: Snapshots verwalten, Vergleich auswählen, Vorschau, Export."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import QDate, Qt, QThread, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QAbstractItemView, QDateEdit, QDialog, QDialogButtonBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QProgressDialog, QPushButton, QScrollArea, QSplitter,
                               QStatusBar, QTabWidget, QVBoxLayout, QWidget)

from .. import config, demo_data, metrics, report
from ..model import Snapshot
from ..snapshot_store import SnapshotStore


class ImportDialog(QDialog):
    """Stichtag und Bezeichnung für einen Import abfragen."""

    def __init__(self, file: Path, default_date: date | None, parent=None, date_source: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Snapshot importieren")
        form = QFormLayout(self)
        form.addRow("Datei:", QLabel(file.name))
        self.date_edit = QDateEdit(calendarPopup=True)
        self.date_edit.setDisplayFormat("dd.MM.yyyy")
        d = default_date or date.today()
        self.date_edit.setDate(QDate(d.year, d.month, d.day))
        form.addRow("Stichtag:", self.date_edit)
        hint = f"Vorschlag {d.strftime('%d.%m.%Y')}" + (f" ({date_source})" if date_source else "")
        hint_label = QLabel(f"{hint} – mit OK bestätigen oder ändern")
        hint_label.setStyleSheet("color: #666666")
        form.addRow("", hint_label)
        self.label_edit = QLineEdit()
        self.label_edit.setPlaceholderText("z. B. Wochenreview")
        form.addRow("Bezeichnung:", self.label_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    @property
    def snapshot_date(self) -> date:
        q = self.date_edit.date()
        return date(q.year(), q.month(), q.day())

    @property
    def label(self) -> str:
        return self.label_edit.text().strip()


def _qdate(d: date) -> QDate:
    return QDate(d.year, d.month, d.day)


def _pydate(q: QDate) -> date:
    return date(q.year(), q.month(), q.day())


class ImportWorker(QThread):
    """Liest eine MS-Project-Datei im Hintergrund (JVM-Start + MPXJ-Parsing können bei
    großen Master-Dateien mit vielen Unterdateien mehrere Sekunden dauern – ohne
    Hintergrund-Thread friert währenddessen die ganze Oberfläche ein)."""
    loaded = Signal(object, list)
    failed = Signal(str)

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self) -> None:
        try:
            from ..reader import read_snapshot
            snap, warnings = read_snapshot(self.path)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.loaded.emit(snap, warnings)


class ChartTab(QWidget):
    PX_PER_WEEK = 16      # Master Timeline: ab dieser Dichte horizontal scrollen

    def __init__(self, builder, parent=None):
        super().__init__(parent)
        self.builder = builder
        self.figure = Figure(figsize=report.FIG_SIZE)
        self.canvas = FigureCanvas(self.figure)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.canvas)
        lay.addWidget(self.scroll)

    def render(self, review: report.Review | None) -> None:
        self.figure.set_size_inches(*report.FIG_SIZE, forward=False)
        self.figure.clear()
        # lange Zeitachsen (Master Timeline) horizontal scrollbar machen
        weeks = len(review.week_points) if review is not None and self.builder is report.figure_timeline else 0
        self.canvas.setMinimumWidth(weeks * self.PX_PER_WEEK if weeks > 60 else 0)
        if review is not None:
            self.builder(review, self.figure)
        else:
            ax = self.figure.add_subplot(111)
            ax.axis("off")
            ax.text(0.5, 0.5, "Snapshots links auswählen und „Vorschau aktualisieren“ klicken",
                    ha="center", va="center", color="#777777")
        # lange Überfälligen-Liste vertikal scrollbar machen (figure_overdue_list vergrößert
        # die Figure ggf. auf die volle Zeilenzahl, statt Zeilen abzuschneiden)
        if self.builder is report.figure_overdue_list:
            dpi = self.figure.dpi
            self.canvas.setMinimumHeight(int(self.figure.get_figheight() * dpi))
        else:
            self.canvas.setMinimumHeight(0)
        self.canvas.draw_idle()


class MainWindow(QMainWindow):
    def __init__(self, db_path: str | None = None):
        super().__init__()
        self.setWindowTitle("MPP-Auswertungstool – PJM Project Review")
        self.resize(1400, 850)
        self.store = SnapshotStore(db_path)
        self.review: report.Review | None = None
        self._snap_cache: dict[int, Snapshot] = {}
        self._filling_groups = False
        self._setting_dates = False
        self._import_worker: ImportWorker | None = None
        self._build_ui()
        self._build_menu()
        self.refresh_snapshot_list()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        # linke Seite: Snapshots
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.addWidget(QLabel("<b>1. Input</b>"))
        row = QHBoxLayout()
        self.btn_import = QPushButton("MS-Project-Datei importieren…")
        self.btn_import.clicked.connect(self.import_file)
        self.btn_demo = QPushButton("Demo-Daten")
        self.btn_demo.clicked.connect(self.load_demo)
        row.addWidget(self.btn_import)
        row.addWidget(self.btn_demo)
        ll.addLayout(row)

        ll.addWidget(QLabel("<b>2. Vergleichsauswahl</b> – Snapshots ankreuzen (letzter = aktuell)"))
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.itemChanged.connect(self.refresh_group_list)
        ll.addWidget(self.list, 1)
        row2 = QHBoxLayout()
        b_all = QPushButton("Alle")
        b_all.clicked.connect(lambda: self._check_all(True))
        b_none = QPushButton("Keine")
        b_none.clicked.connect(lambda: self._check_all(False))
        b_del = QPushButton("Löschen")
        b_del.clicked.connect(self.delete_selected)
        row2.addWidget(b_all)
        row2.addWidget(b_none)
        row2.addStretch()
        row2.addWidget(b_del)
        ll.addLayout(row2)

        form = QFormLayout()
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Projektname im Bericht")
        form.addRow("Projekt:", self.name_edit)
        self.report_date_edit = QDateEdit(calendarPopup=True)
        self.report_date_edit.setDisplayFormat("dd.MM.yyyy")
        self.report_date_edit.setDate(_qdate(date.today()))
        self.report_date_edit.setToolTip("Stichtag der Auswertung (Standard: heute) – bestimmt die Auswertungswoche")
        form.addRow("Auswertungsdatum:", self.report_date_edit)
        self.week_from_edit = QDateEdit(calendarPopup=True)
        self.week_to_edit = QDateEdit(calendarPopup=True)
        row_w = QHBoxLayout()
        for ed in (self.week_from_edit, self.week_to_edit):
            ed.setDisplayFormat("dd.MM.yyyy")
            ed.setToolTip("Zeitraum der Master Timeline – es zählt die Kalenderwoche des Datums")
        row_w.addWidget(self.week_from_edit)
        row_w.addWidget(QLabel("bis"))
        row_w.addWidget(self.week_to_edit)
        form.addRow("Timeline von:", row_w)
        self.week_range_label = QLabel()
        self.week_range_label.setStyleSheet("color: #666666")
        form.addRow("", self.week_range_label)
        b_range = QPushButton("Zeitraum zurücksetzen (erste Snapshot-KW bis Planende)")
        b_range.clicked.connect(self.reset_week_range)
        form.addRow("", b_range)
        # neues Auswertungsdatum verschiebt die Auswertungswoche -> Zeitraum neu bestimmen
        self.report_date_edit.dateChanged.connect(self.reset_week_range)
        for ed in (self.week_from_edit, self.week_to_edit):
            ed.dateChanged.connect(self._on_dates_changed)
        ll.addLayout(form)

        self.group_label = QLabel()
        ll.addWidget(self.group_label)
        self.group_list = QListWidget()
        self.group_list.setToolTip("Wirkt auf die Gruppen-Folien in Vorschau und Export: Aufgaben/Überfällige "
                                   "je Fachabteilung, Top-Overdues, Liste überfälliger Aufgaben")
        self.group_list.itemChanged.connect(self._on_group_changed)
        ll.addWidget(self.group_list, 1)
        row_g = QHBoxLayout()
        g_all = QPushButton("Alle")
        g_all.clicked.connect(lambda: self._check_all_groups(True))
        g_none = QPushButton("Keine")
        g_none.clicked.connect(lambda: self._check_all_groups(False))
        row_g.addWidget(g_all)
        row_g.addWidget(g_none)
        row_g.addStretch()
        ll.addLayout(row_g)
        self._update_group_label()

        ll.addWidget(QLabel("<b>3. Vorschau</b>"))
        self.btn_preview = QPushButton("Vorschau aktualisieren")
        self.btn_preview.clicked.connect(self.update_preview)
        ll.addWidget(self.btn_preview)

        ll.addWidget(QLabel("<b>4. Export</b>"))
        row3 = QHBoxLayout()
        self.btn_pptx = QPushButton("Als PPTX exportieren…")
        self.btn_pptx.clicked.connect(lambda: self.export("pptx"))
        self.btn_pdf = QPushButton("Als PDF exportieren…")
        self.btn_pdf.clicked.connect(lambda: self.export("pdf"))
        row3.addWidget(self.btn_pptx)
        row3.addWidget(self.btn_pdf)
        ll.addLayout(row3)
        splitter.addWidget(left)

        # rechte Seite: Kopfzeile + Vorschau-Tabs
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.header_label = QLabel()
        self.header_label.setStyleSheet("padding: 4px; color: #333333; background: #eeeeee")
        rl.addWidget(self.header_label)
        self.tabs = QTabWidget()
        self.chart_tabs: list[ChartTab] = []
        for title, builder in report.SLIDE_BUILDERS:
            tab = ChartTab(builder)
            self.chart_tabs.append(tab)
            self.tabs.addTab(tab, title)
        rl.addWidget(self.tabs, 1)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([380, 1000])

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage(f"Datenbank: {self.store.db_path}")
        for t in self.chart_tabs:
            t.render(None)

    def _build_menu(self) -> None:
        m = self.menuBar().addMenu("&Datei")
        a = QAction("Importieren…", self)
        a.triggered.connect(self.import_file)
        m.addAction(a)
        a = QAction("Demo-Daten laden", self)
        a.triggered.connect(self.load_demo)
        m.addAction(a)
        m.addSeparator()
        a = QAction("Beenden", self)
        a.triggered.connect(self.close)
        m.addAction(a)
        h = self.menuBar().addMenu("&Hilfe")
        a = QAction("Über", self)
        a.triggered.connect(lambda: QMessageBox.information(
            self, "Über", "MPP-Auswertungstool – Prototyp\n\nEinlesen von MS-Project-Dateien (MPXJ), "
                          "Historisierung als Snapshots (SQLite), Bewertung und PJM-Review-Bericht (PPTX/PDF)."))
        h.addAction(a)

    # ------------------------------------------------------------ Snapshots
    def refresh_snapshot_list(self, check_new: bool = False) -> None:
        checked = {self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                   if self.list.item(i).checkState() == Qt.Checked}
        self.list.clear()
        for s in self.store.list_snapshots():
            item = QListWidgetItem(f"#{s.snapshot_id}  {s.display_name}   [{s.source_file}]")
            item.setData(Qt.UserRole, s.snapshot_id)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if (s.snapshot_id in checked or check_new) else Qt.Unchecked)
            self.list.addItem(item)
        self.refresh_group_list()

    def _check_all(self, state: bool) -> None:
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.Checked if state else Qt.Unchecked)

    def checked_ids(self) -> list[int]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]

    def import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "MS-Project-Datei wählen", "",
            "MS Project (*.mpp *.xml *.mpx *.mpt);;Alle Dateien (*)")
        if not path:
            return
        self._start_import(Path(path))

    def _start_import(self, p: Path) -> None:
        # Import läuft im Hintergrund-Thread (JVM-Start + MPXJ-Parsing können bei großen
        # Master-Dateien mehrere Sekunden dauern) – währenddessen eine Fortschrittsanzeige
        # statt eines nur per Wait-Cursor "eingefrorenen" Fensters.
        self.btn_import.setEnabled(False)
        progress = QProgressDialog(
            f"Importiere {p.name}…\n(beim ersten Import startet zusätzlich die Java-Laufzeit"
            " – das kann einen Moment dauern)", None, 0, 0, self)
        progress.setWindowTitle("Import läuft")
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.show()

        worker = ImportWorker(p, self)
        self._import_worker = worker   # Referenz halten, sonst wird der Thread vorzeitig freigegeben

        def on_loaded(snap, warnings) -> None:
            progress.close()
            self.btn_import.setEnabled(True)
            self._import_worker = None
            self._finish_import(p, snap, warnings)

        def on_failed(message: str) -> None:
            progress.close()
            self.btn_import.setEnabled(True)
            self._import_worker = None
            QMessageBox.critical(self, "Import fehlgeschlagen", message)

        worker.loaded.connect(on_loaded)
        worker.failed.connect(on_failed)
        worker.start()

    def _finish_import(self, p: Path, snap: Snapshot, warnings: list[str]) -> None:
        dlg = ImportDialog(p, snap.snapshot_date, self, snap.date_source)
        if dlg.exec() != QDialog.Accepted:
            return
        snap.snapshot_date = dlg.snapshot_date
        snap.label = dlg.label
        sid = self.store.add_snapshot(snap)
        self.refresh_snapshot_list()
        self._check_id(sid)
        msg = f"Snapshot #{sid} importiert ({len(snap.tasks)} Aufgaben)."
        if warnings:
            QMessageBox.warning(self, "Import mit Hinweisen", msg + "\n\n" + "\n".join(warnings))
        self.statusBar().showMessage(msg)

    def _check_id(self, sid: int) -> None:
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == sid:
                self.list.item(i).setCheckState(Qt.Checked)

    def load_demo(self) -> None:
        for s in demo_data.generate_snapshots():
            self.store.add_snapshot(s)
        self.refresh_snapshot_list(check_new=True)
        if not self.name_edit.text():
            self.name_edit.setText("Demo-Projekt")
        self.statusBar().showMessage("6 synthetische Wochen-Snapshots geladen.")
        self.update_preview()

    def delete_selected(self) -> None:
        items = self.list.selectedItems()
        if not items:
            QMessageBox.information(self, "Löschen", "Bitte Snapshots in der Liste markieren.")
            return
        if QMessageBox.question(self, "Löschen", f"{len(items)} Snapshot(s) endgültig löschen?") != QMessageBox.Yes:
            return
        for it in items:
            sid = it.data(Qt.UserRole)
            self.store.delete_snapshot(sid)
            self._snap_cache.pop(sid, None)
        self.refresh_snapshot_list()

    def _checked_snapshots(self) -> list[Snapshot]:
        snaps = []
        for sid in self.checked_ids():
            if sid not in self._snap_cache:
                self._snap_cache[sid] = self.store.load_snapshot(sid)
            snaps.append(self._snap_cache[sid])
        return sorted(snaps, key=lambda s: (s.snapshot_date, s.snapshot_id))

    # ---------------------------------------------------- Ressourcengruppen
    def refresh_group_list(self, *_args) -> None:
        """Gruppen der angekreuzten Snapshots auflisten; bisherige An-/Abwahl bleibt
        erhalten, neu hinzukommende Gruppen sind angekreuzt."""
        previous = {self.group_list.item(i).text(): self.group_list.item(i).checkState()
                    for i in range(self.group_list.count())}
        self._filling_groups = True
        try:
            self.group_list.clear()
            for dep in metrics.all_departments(self._checked_snapshots()):
                item = QListWidgetItem(dep)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(previous.get(dep, Qt.Checked))
                self.group_list.addItem(item)
        finally:
            self._filling_groups = False
        self._update_group_label()
        self.reset_week_range()

    def _check_all_groups(self, state: bool) -> None:
        self._filling_groups = True
        try:
            for i in range(self.group_list.count()):
                self.group_list.item(i).setCheckState(Qt.Checked if state else Qt.Unchecked)
        finally:
            self._filling_groups = False
        self._on_group_changed()

    def selected_groups(self) -> set[str] | None:
        """Angekreuzte Gruppen; None, wenn alle angekreuzt sind (= kein Filter)."""
        items = [self.group_list.item(i) for i in range(self.group_list.count())]
        checked = {it.text() for it in items if it.checkState() == Qt.Checked}
        return None if len(checked) == len(items) else checked

    def _update_group_label(self) -> None:
        n = self.group_list.count()
        k = sum(1 for i in range(n) if self.group_list.item(i).checkState() == Qt.Checked)
        self.group_label.setText(f"<b>Ressourcengruppen</b> – {k} von {n} ausgewählt (Gruppen-Folien)")

    def _on_group_changed(self, *_args) -> None:
        if self._filling_groups:
            return
        self._update_group_label()
        if self.review is not None and self.checked_ids():
            self.update_preview()

    # ------------------------------------------------- Auswertungsdatum / KW
    def reset_week_range(self, *_args) -> None:
        """Zeitraum auf erste Snapshot-KW bis Planende des aktuellen Plans setzen."""
        snaps = self._checked_snapshots()
        if not snaps:
            self._update_week_label()
            return
        rv = report.build_review(snaps, report_date=_pydate(self.report_date_edit.date()))
        if rv.week_points:
            self._setting_dates = True
            try:
                self.week_from_edit.setDate(_qdate(rv.week_points[0].start))
                self.week_to_edit.setDate(_qdate(rv.week_points[-1].start))
            finally:
                self._setting_dates = False
        self._on_dates_changed()

    def _update_week_label(self) -> None:
        wf, wt = _pydate(self.week_from_edit.date()), _pydate(self.week_to_edit.date())
        weeks = (metrics.week_start(wt) - metrics.week_start(wf)).days // 7 + 1
        self.week_range_label.setText(f"{metrics.week_label(wf, True)} – {metrics.week_label(wt, True)} "
                                      f"({max(weeks, 0)} Wochen)")

    def _on_dates_changed(self, *_args) -> None:
        if self._setting_dates:
            return
        self._update_week_label()
        if self.review is not None and self.checked_ids():
            self.update_preview()

    # ------------------------------------------------------------- Vorschau
    def _build_review(self) -> report.Review | None:
        if not self.checked_ids():
            QMessageBox.information(self, "Vorschau", "Bitte mindestens einen Snapshot ankreuzen.")
            return None
        return report.build_review(self._checked_snapshots(), self.name_edit.text().strip() or None,
                                   report_date=_pydate(self.report_date_edit.date()),
                                   departments=self.selected_groups(),
                                   week_from=_pydate(self.week_from_edit.date()),
                                   week_to=_pydate(self.week_to_edit.date()))

    def update_preview(self) -> None:
        self.review = self._build_review()
        for t in self.chart_tabs:
            t.render(self.review)
        self.header_label.setText(self.review.header if self.review else "")
        if self.review:
            m = self.review.current
            self.statusBar().showMessage(
                f"Stichtag {self.review.cur_label}: {m.monitored} Aufgaben "
                f"({m.tasks_count} Aufgaben / {m.milestones_count} Meilensteine) · "
                f"{m.actually_closed}/{m.planned_closed} geschlossen ({m.fulfilment_pct:.1f} %) · "
                f"{m.open_overdue} überfällig · {m.hold} Hold · {m.cancelled} Cancelled · "
                f"{m.no_group_count} ohne Ressourcengruppe (nicht gezählt) · "
                f"Vergleich zu {self.review.prev_label}")

    # --------------------------------------------------------------- Export
    def export(self, kind: str) -> None:
        # immer mit der aktuellen Snapshot- und Gruppenauswahl neu aufbauen,
        # damit Export und Vorschau übereinstimmen
        self.update_preview()
        if self.review is None:
            return
        default = config.OUTPUT_DIR / self.review.default_filename(kind)
        flt = "PowerPoint (*.pptx)" if kind == "pptx" else "PDF (*.pdf)"
        path, _ = QFileDialog.getSaveFileName(self, "Exportieren", str(default), flt)
        if not path:
            return
        try:
            if kind == "pptx":
                report.export_pptx(self.review, path)
            else:
                report.export_pdf(self.review, path)
        except Exception as exc:
            QMessageBox.critical(self, "Export fehlgeschlagen", str(exc))
            return
        self.statusBar().showMessage(f"Exportiert: {path}")

    def closeEvent(self, event) -> None:
        if self._import_worker is not None:
            self._import_worker.wait()
        self.store.close()
        super().closeEvent(event)
