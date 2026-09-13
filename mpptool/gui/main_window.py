"""Hauptfenster: Snapshots verwalten, Vergleich auswählen, Vorschau, Export."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDateEdit, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSplitter,
                               QStatusBar, QTabWidget, QVBoxLayout, QWidget)

from .. import config, demo_data, report
from ..model import Snapshot
from ..snapshot_store import SnapshotStore


class ImportDialog(QDialog):
    """Stichtag und Bezeichnung für einen Import abfragen."""

    def __init__(self, file: Path, default_date: date | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Snapshot importieren")
        form = QFormLayout(self)
        form.addRow("Datei:", QLabel(file.name))
        self.date_edit = QDateEdit(calendarPopup=True)
        d = default_date or date.today()
        self.date_edit.setDate(QDate(d.year, d.month, d.day))
        form.addRow("Stichtag:", self.date_edit)
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


class ChartTab(QWidget):
    def __init__(self, builder, parent=None):
        super().__init__(parent)
        self.builder = builder
        self.figure = Figure(figsize=report.FIG_SIZE)
        self.canvas = FigureCanvas(self.figure)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.canvas)

    def render(self, review: report.Review | None) -> None:
        self.figure.clear()
        if review is not None:
            self.builder(review, self.figure)
        else:
            ax = self.figure.add_subplot(111)
            ax.axis("off")
            ax.text(0.5, 0.5, "Snapshots links auswählen und „Vorschau aktualisieren“ klicken",
                    ha="center", va="center", color="#777777")
        self.canvas.draw_idle()


class MainWindow(QMainWindow):
    def __init__(self, db_path: str | None = None):
        super().__init__()
        self.setWindowTitle("MPP-Auswertungstool – PJM Project Review")
        self.resize(1400, 850)
        self.store = SnapshotStore(db_path)
        self.review: report.Review | None = None
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
        ll.addLayout(form)

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

        # rechte Seite: Vorschau-Tabs
        self.tabs = QTabWidget()
        self.chart_tabs: list[ChartTab] = []
        for title, builder in report.SLIDE_BUILDERS:
            tab = ChartTab(builder)
            self.chart_tabs.append(tab)
            self.tabs.addTab(tab, title)
        splitter.addWidget(self.tabs)
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
        p = Path(path)
        try:
            from ..reader import read_snapshot
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                snap, warnings = read_snapshot(p)
            finally:
                QApplication.restoreOverrideCursor()
        except Exception as exc:
            QMessageBox.critical(self, "Import fehlgeschlagen", str(exc))
            return
        dlg = ImportDialog(p, snap.snapshot_date, self)
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
            self.store.delete_snapshot(it.data(Qt.UserRole))
        self.refresh_snapshot_list()

    # ------------------------------------------------------------- Vorschau
    def _build_review(self) -> report.Review | None:
        ids = self.checked_ids()
        if not ids:
            QMessageBox.information(self, "Vorschau", "Bitte mindestens einen Snapshot ankreuzen.")
            return None
        snaps: list[Snapshot] = self.store.load_snapshots(ids)
        return report.build_review(snaps, self.name_edit.text().strip() or None)

    def update_preview(self) -> None:
        self.review = self._build_review()
        for t in self.chart_tabs:
            t.render(self.review)
        if self.review:
            m = self.review.current
            self.statusBar().showMessage(
                f"{self.review.cur_label}: {m.monitored} Aufgaben · {m.actually_closed}/{m.planned_closed} geschlossen "
                f"({m.fulfilment_pct:.1f} %) · {m.open_overdue} überfällig · {m.hold} Hold · "
                f"Vergleich zu {self.review.prev_label}")

    # --------------------------------------------------------------- Export
    def export(self, kind: str) -> None:
        if self.review is None:
            self.update_preview()
            if self.review is None:
                return
        default = config.OUTPUT_DIR / f"review_{self.review.cur_label}.{kind}"
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
        self.store.close()
        super().closeEvent(event)
