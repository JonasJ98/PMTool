"""Berichtserzeugung im PJM-Review-Layout – PPTX (python-pptx) und PDF (matplotlib).

Ablauf: ``build_review(snapshots)`` berechnet Kennzahlen und liefert ein
``Review``-Objekt. Daraus rendern ``export_pptx`` und ``export_pdf`` die Folien;
die GUI-Vorschau nutzt dieselben Chart-Funktionen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Inches, Pt

from . import charts, config
from .metrics import (FinishPoint, OverdueTrendRow, SnapshotMetrics, TimelinePoint, WeekPoint, all_departments,
                      compute_metrics, finish_trend, master_timeline, overdue_tasks, overdue_trend, task_changes,
                      timeline, week_label)
from .model import Snapshot, TaskRecord

SLIDE_W, SLIDE_H = Inches(13.333), Inches(7.5)   # 16:9
FIG_SIZE = (12.5, 5.6)                             # Zoll, passend zur Folie

_STATUS_GOOD = "#2ca02c"
_STATUS_WARN = "#d4ac00"
_STATUS_BAD = "#d62728"


@dataclass
class Review:
    project_name: str
    metrics: list[SnapshotMetrics]           # chronologisch
    timeline: list[TimelinePoint]
    trend_rows: list[OverdueTrendRow]
    overdue_list: list[TaskRecord]
    report_date: date = field(default_factory=date.today)
    changes: dict[str, list[TaskRecord]] = field(default_factory=dict)
    # Ressourcengruppen-Auswahl für die Gruppen-Folien (None = alle Gruppen)
    departments: frozenset[str] | None = None
    all_departments: list[str] = field(default_factory=list)
    finish_points: list[FinishPoint] = field(default_factory=list)
    week_points: list[WeekPoint] = field(default_factory=list)   # Master Timeline je KW

    @property
    def current(self) -> SnapshotMetrics:
        return self.metrics[-1]

    @property
    def previous(self) -> SnapshotMetrics | None:
        return self.metrics[-2] if len(self.metrics) > 1 else None

    @property
    def timeline_file(self) -> str:
        return self.current.snapshot.source_file

    @property
    def header(self) -> str:
        """Kopfzeile (Besprechung): Projekt, Timeline-Datei, Auswertungsdatum + KW."""
        d = self.current.as_of
        return (f"Projekt: {self.project_name}  ·  Timeline: {self.timeline_file}  ·  "
                f"Auswertungsdatum: {d.strftime('%d.%m.%Y')} ({week_label(d, True)})")

    def default_filename(self, ext: str) -> str:
        import re
        kw = week_label(self.current.as_of)
        name = re.sub(r'[\\/:*?"<>|]+', "_", self.project_name).strip() or "Projekt"
        return f"{name}_Review_{kw}_{self.current.as_of.isoformat()}.{ext}"

    @property
    def group_suffix(self) -> str:
        """Titelzusatz, wenn nur ein Teil der Ressourcengruppen ausgewählt ist."""
        if self.departments is None:
            return ""
        n = sum(1 for d in self.all_departments if d in self.departments)
        if n == len(self.all_departments):
            return ""
        return f" (Auswahl: {n} von {len(self.all_departments)} Gruppen)"

    @property
    def prev_label(self) -> str:
        return self.previous.as_of.isoformat() if self.previous else "-"

    @property
    def cur_label(self) -> str:
        return self.current.as_of.isoformat()


def build_review(snapshots: list[Snapshot], project_name: str | None = None,
                 report_date: date | None = None, departments: Iterable[str] | None = None,
                 week_from: date | None = None, week_to: date | None = None) -> Review:
    """Baut den Bericht. Der aktuelle Vergleichspunkt wird immer zum Auswertungstag
    (``report_date``, Standard: heute) bewertet – unabhängig von der Kalenderwoche
    des zuletzt importierten Snapshots. Der Vergleich erfolgt stets gegen den
    letzten (chronologisch vorherigen) Stichtag.

    ``departments`` beschränkt die Gruppen-Folien (Aufgaben/Überfällige je
    Fachabteilung, Top-Overdues, Liste überfälliger Aufgaben) auf die gewählten
    Ressourcengruppen; Übersicht und Master Timeline zeigen das Gesamtprojekt.

    ``week_from``/``week_to`` begrenzen die Master Timeline (KW von–bis); Standard:
    erste Snapshot-KW bis Planende."""
    if not snapshots:
        raise ValueError("Mindestens ein Snapshot erforderlich")
    report_date = report_date or date.today()
    snaps = sorted(snapshots, key=lambda s: (s.snapshot_date, s.snapshot_id or 0))
    ms = [compute_metrics(s) for s in snaps[:-1]]
    ms.append(compute_metrics(snaps[-1], as_of=report_date))
    prev = ms[-2] if len(ms) > 1 else None
    name = project_name or Path(snaps[-1].source_file).stem
    deps = frozenset(departments) if departments is not None else None
    return Review(
        project_name=name, metrics=ms, timeline=timeline(ms), report_date=report_date,
        trend_rows=overdue_trend(ms, departments=deps), overdue_list=overdue_tasks(ms[-1], deps),
        changes=task_changes(prev, ms[-1]), departments=deps, all_departments=all_departments(snaps),
        finish_points=finish_trend(ms), week_points=master_timeline(ms, week_from, week_to),
    )


# --------------------------------------------------------------------------
# Folien als Figuren (gemeinsame Basis für Vorschau und PDF)
# --------------------------------------------------------------------------
def figure_timeline(review: Review, fig: Figure | None = None) -> Figure:
    fig = fig or Figure(figsize=FIG_SIZE)
    return charts.draw_master_timeline(fig, review.week_points, f"Master Timeline – {review.project_name}")


def figure_finish_trend(review: Review, fig: Figure | None = None) -> Figure:
    fig = fig or Figure(figsize=FIG_SIZE)
    return charts.draw_finish_trend(fig, review.finish_points,
                                    f"Verschiebung des erwarteten Projektendes – {review.project_name}")


def figure_department_status(review: Review, fig: Figure | None = None) -> Figure:
    fig = fig or Figure(figsize=FIG_SIZE)
    return charts.draw_department_status(fig, review.current, "Aufgaben je Fachabteilung" + review.group_suffix,
                                         departments=review.departments)


def figure_overdue_by_department(review: Review, fig: Figure | None = None) -> Figure:
    fig = fig or Figure(figsize=FIG_SIZE)
    return charts.draw_overdue_by_department(fig, review.current, review.previous,
                                             "Überfällige Aufgaben je Fachabteilung" + review.group_suffix,
                                             departments=review.departments)


def figure_trend_table(review: Review, fig: Figure | None = None) -> Figure:
    fig = fig or Figure(figsize=FIG_SIZE)
    return charts.draw_overdue_trend_table(
        fig, review.trend_rows, review.prev_label, review.cur_label,
        f"Top-{config.TOP_N_OVERDUES} Overdues mit Trendanalyse – {review.prev_label} vs. {review.cur_label}"
        f"{review.group_suffix}")


def _overdue_rows(tasks: list[TaskRecord], as_of: date) -> list[list[str]]:
    rows = []
    for t in tasks:
        days = (as_of - t.finish).days if t.finish else 0
        rows.append([t.department, t.wbs or "-", t.name, t.finish.isoformat() if t.finish else "-", f"{days} d",
                     f"{t.percent_complete:.0f} %"])
    return rows


def _draw_overdue_table(ax, rows: list[list[str]], fontsize: int = 8) -> None:
    tbl = ax.table(cellText=rows, colLabels=["Abteilung", "PSP-Code", "Aufgabe", "Geplantes Ende", "Verzug", "Fortschritt"],
                   loc="upper center", cellLoc="left", colWidths=[0.11, 0.1, 0.43, 0.13, 0.09, 0.11])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(fontsize)
    tbl.scale(1, 1.25)
    for (r, c), cell in tbl.get_celld().items():
        if r == 0:
            cell.set_facecolor("#dddddd")
            cell.set_text_props(fontweight="bold")


OVERDUE_ROWS_PER_PDF_PAGE = 18     # matplotlib-Tabelle (bisheriges Format, unverändert)
OVERDUE_ROWS_PER_PPTX_SLIDE = 13   # native PPTX-Tabelle (feste Zeilenhöhe von 0.4")


def overdue_pages(review: Review, page_size: int) -> list[list[TaskRecord]]:
    """Überfällige Aufgaben in feste Seiten aufgeteilt – für PDF/PPTX, die (anders als
    die scrollbare GUI-Vorschau) nicht scrollen können und sonst Zeilen jenseits der
    ersten Seite stillschweigend verlieren würden."""
    tasks = review.overdue_list
    if not tasks:
        return [[]]
    return [tasks[i:i + page_size] for i in range(0, len(tasks), page_size)]


def figure_overdue_list_page(review: Review, tasks: list[TaskRecord], page: int, total_pages: int,
                             fig: Figure | None = None) -> Figure:
    """Eine Export-Seite der Überfälligen-Liste mit fester Zeilenzahl (PDF/PPTX)."""
    fig = fig or Figure(figsize=FIG_SIZE)
    fig.clear()
    ax = fig.add_subplot(111)
    ax.axis("off")
    suffix = f" – Seite {page + 1}/{total_pages}" if total_pages > 1 else ""
    ax.set_title(f"Überfällige Aufgaben – {review.cur_label} ({len(review.overdue_list)}){review.group_suffix}{suffix}",
                 fontweight="bold", loc="left")
    rows = _overdue_rows(tasks, review.current.as_of)
    if not rows:
        ax.text(0.5, 0.5, "Keine überfälligen Aufgaben", ha="center", va="center")
        return fig
    _draw_overdue_table(ax, rows)
    return fig


def figure_overdue_list(review: Review, fig: Figure | None = None) -> Figure:
    """GUI-Vorschau: die vollständige Liste in einer ausreichend hohen Figure – der Tab
    stellt sie über eine Scrollbar dar (ChartTab), statt Zeilen abzuschneiden. PDF/PPTX
    können nicht scrollen und zeigen dieselben Zeilen stattdessen seitenweise, siehe
    ``overdue_pages``/``figure_overdue_list_page``."""
    tasks = review.overdue_list
    n = max(len(tasks), 1)
    height = max(FIG_SIZE[1], 0.9 + n * 0.22)
    fig = fig or Figure(figsize=(FIG_SIZE[0], height))
    fig.set_size_inches(FIG_SIZE[0], height, forward=True)
    fig.clear()
    ax = fig.add_subplot(111)
    ax.axis("off")
    ax.set_title(f"Überfällige Aufgaben – {review.cur_label} ({len(tasks)}){review.group_suffix}",
                 fontweight="bold", loc="left")
    rows = _overdue_rows(tasks, review.current.as_of)
    if not rows:
        ax.text(0.5, 0.5, "Keine überfälligen Aufgaben", ha="center", va="center")
        return fig
    _draw_overdue_table(ax, rows, fontsize=9)
    return fig


def figure_kpis(review: Review, fig: Figure | None = None) -> Figure:
    fig = fig or Figure(figsize=FIG_SIZE)
    fig.clear()
    m = review.current
    ax = fig.add_subplot(111)
    ax.axis("off")
    ax.set_title(f"{config.REPORT_TITLE} – {review.project_name}", fontweight="bold", loc="left", fontsize=16)
    # Erfüllungsgrad/Überfällig sind die beiden Werte, nach denen ein PJM-Review zuerst
    # schaut – farblich hervorgehoben, damit ein kritischer Stand sofort auffällt statt
    # zwischen 12 gleich aussehenden Zahlen unterzugehen.
    fulfilment_color = (_STATUS_GOOD if m.fulfilment_pct >= 100 else
                        _STATUS_WARN if m.fulfilment_pct >= 80 else _STATUS_BAD)
    overdue_color = _STATUS_GOOD if m.open_overdue == 0 else _STATUS_BAD
    kpis = [
        ("Stichtag (Auswertungstag)", m.as_of.isoformat(), None),
        ("Überwachte Aufgaben", str(m.monitored), None),
        ("davon Aufgaben (>0 Tage)", str(m.tasks_count), None),
        ("davon Meilensteine", str(m.milestones_count), None),
        ("Geplant geschlossen", str(m.planned_closed), None),
        ("Tatsächlich geschlossen", str(m.actually_closed), None),
        ("Erfüllungsgrad", f"{m.fulfilment_pct:.1f} %", fulfilment_color),
        ("Überfällig (offen)", str(m.open_overdue), overdue_color),
        ("Verspätet geschlossen", str(m.closed_overdue), None),
        ("Hold", str(m.hold), None),
        ("Cancelled", str(m.cancelled), None),
        ("Fachabteilungen", str(len(m.departments)), None),
        ("Ohne Ressourcengruppe", str(m.no_group_count), None),
        ("Snapshots im Vergleich", str(len(review.metrics)), None),
    ]
    # Label über Wert statt nebeneinander – so überlappt eine lange Bezeichnung nie mit
    # der Zahl (bei fester Spaltenbreite kann das rechts danebenstehende Textfeld sonst
    # mit langen Labels wie „Stichtag (Auswertungstag)“ kollidieren).
    rows_per_col = 5
    for i, (k, v, color) in enumerate(kpis):
        col, row = divmod(i, rows_per_col)
        x = 0.03 + col * 0.34
        y = 0.82 - row * 0.165
        ax.text(x, y, k, fontsize=10, color="#555555", transform=ax.transAxes)
        ax.text(x, y - 0.065, v, fontsize=15, fontweight="bold", color=color or "#111111", transform=ax.transAxes)
    return fig


SLIDE_BUILDERS = [
    ("Übersicht", figure_kpis),
    ("Master Timeline", figure_timeline),
    ("Projektende-Trend", figure_finish_trend),
    ("Aufgaben je Fachabteilung", figure_department_status),
    ("Überfällige je Fachabteilung", figure_overdue_by_department),
    ("Top-Overdues Trend", figure_trend_table),
    ("Überfällige Aufgaben", figure_overdue_list),
]


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def export_pdf(review: Review, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with PdfPages(str(path)) as pdf:
        for _title, builder in SLIDE_BUILDERS:
            if builder is figure_overdue_list:
                continue   # seitenweise statt abgeschnitten, siehe unten
            fig = builder(review, Figure(figsize=(13.333, 7.5)))
            _footer_fig(fig, review)
            pdf.savefig(fig)
        pages = overdue_pages(review, OVERDUE_ROWS_PER_PDF_PAGE)
        for i, chunk in enumerate(pages):
            fig = figure_overdue_list_page(review, chunk, i, len(pages), Figure(figsize=(13.333, 7.5)))
            _footer_fig(fig, review)
            pdf.savefig(fig)
        d = pdf.infodict()
        d["Title"] = f"{config.REPORT_TITLE} – {review.project_name}"
        d["Author"] = config.REPORT_AUTHOR
    return path


def _footer_fig(fig: Figure, review: Review) -> None:
    fig.text(0.99, 0.995, review.header, fontsize=7, color="#888888", va="top", ha="right")


# --------------------------------------------------------------------------
# PPTX
# --------------------------------------------------------------------------
def export_pptx(review: Review, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H
    blank = prs.slide_layouts[6]

    # Titelfolie
    s = prs.slides.add_slide(blank)
    _textbox(s, config.REPORT_TITLE, Inches(0.6), Inches(2.4), Inches(12), Inches(1.0), 40, bold=True)
    _textbox(s, review.project_name, Inches(0.6), Inches(3.4), Inches(12), Inches(0.8), 24)
    _textbox(s, f"Timeline: {review.timeline_file}\n"
                f"Auswertungsdatum: {review.current.as_of.strftime('%d.%m.%Y')} ({week_label(review.current.as_of, True)})"
                f" · Vergleich zu {review.prev_label}",
             Inches(0.6), Inches(4.3), Inches(12), Inches(1.0), 16, color="666666")

    # KPI-Folie als native Tabelle
    s = prs.slides.add_slide(blank)
    _title(s, f"Übersicht – {review.cur_label}")
    m = review.current
    kpi = [("Stichtag (Auswertungstag)", m.as_of.isoformat()), ("Überwachte Aufgaben", m.monitored),
           ("davon Aufgaben (>0 Tage)", m.tasks_count), ("davon Meilensteine (0 Tage)", m.milestones_count),
           ("Geplant geschlossen", m.planned_closed), ("Tatsächlich geschlossen", m.actually_closed),
           ("Erfüllungsgrad", f"{m.fulfilment_pct:.1f} %"), ("Überfällig (offen)", m.open_overdue),
           ("Verspätet geschlossen", m.closed_overdue), ("Hold", m.hold), ("Cancelled", m.cancelled),
           ("Ohne Ressourcengruppe (nicht gezählt)", m.no_group_count)]
    kpi_shape = _table(s, [["Kennzahl", "Wert"]] + [[k, str(v)] for k, v in kpi],
                       Inches(0.6), Inches(1.3), Inches(6), [4.0, 2.0])
    # Erfüllungsgrad/Überfällig farblich hervorheben – wie in Vorschau/PDF (figure_kpis)
    fulfilment_color = (_STATUS_GOOD if m.fulfilment_pct >= 100 else
                        _STATUS_WARN if m.fulfilment_pct >= 80 else _STATUS_BAD)
    overdue_color = _STATUS_GOOD if m.open_overdue == 0 else _STATUS_BAD
    _color_table_cell(kpi_shape.table, 1 + [k for k, _ in kpi].index("Erfüllungsgrad"), 1, fulfilment_color)
    _color_table_cell(kpi_shape.table, 1 + [k for k, _ in kpi].index("Überfällig (offen)"), 1, overdue_color)

    # Chart-Folien
    for title, builder in [("Master Timeline", figure_timeline),
                           ("Verschiebung des erwarteten Projektendes", figure_finish_trend),
                           ("Aufgaben je Fachabteilung" + review.group_suffix, figure_department_status),
                           ("Überfällige Aufgaben je Fachabteilung" + review.group_suffix, figure_overdue_by_department)]:
        s = prs.slides.add_slide(blank)
        _title(s, title)
        png = charts.figure_to_png(builder(review, Figure(figsize=FIG_SIZE)))
        _picture(s, png, Inches(0.4), Inches(1.2), Inches(12.5))

    # Trend-Tabelle (mit Verlaufs-/Trendanalyse über alle Snapshots)
    s = prs.slides.add_slide(blank)
    _title(s, f"Top-{config.TOP_N_OVERDUES} Overdues mit Trendanalyse – {review.prev_label} vs. {review.cur_label}"
              f"{review.group_suffix}")
    rows = [["Fachabteilung", review.prev_label, review.cur_label, "Trend", "Verlauf"]]
    rows += [[r.department, str(r.previous), str(r.current), f"{r.arrow} {r.delta:+d}", charts.sparkline(r.history)]
             for r in review.trend_rows]
    if len(rows) == 1:
        rows.append(["Keine überfälligen Aufgaben", "", "", "", ""])
    _table(s, rows, Inches(0.6), Inches(1.3), Inches(9), [3.0, 1.4, 1.4, 1.4, 1.8], font=14)

    # Liste überfälliger Aufgaben – seitenweise, damit bei vielen Überfälligen keine
    # Zeilen stillschweigend von der Folie fallen (PPTX kann nicht scrollen)
    pages = overdue_pages(review, OVERDUE_ROWS_PER_PPTX_SLIDE)
    for i, chunk in enumerate(pages):
        s = prs.slides.add_slide(blank)
        suffix = f" – Seite {i + 1}/{len(pages)}" if len(pages) > 1 else ""
        _title(s, f"Überfällige Aufgaben – {review.cur_label} ({len(review.overdue_list)}){review.group_suffix}{suffix}")
        rows = [["Abteilung", "PSP-Code", "Aufgabe", "Geplantes Ende", "Verzug", "Fortschritt"]]
        rows += _overdue_rows(chunk, review.current.as_of)
        if len(rows) == 1:
            rows.append(["Keine überfälligen Aufgaben", "", "", "", "", ""])
        _table(s, rows, Inches(0.5), Inches(1.2), Inches(12.3), [1.5, 1.3, 5.3, 1.8, 1.2, 1.2], font=10)

    # Veränderungen seit Vorwoche
    if review.previous:
        s = prs.slides.add_slide(blank)
        _title(s, f"Veränderungen {review.prev_label} → {review.cur_label}")
        ch = review.changes
        lines = [f"Neu überfällig: {len(ch['newly_overdue'])}"] + [f"   • {t.department} – {t.name}" for t in ch["newly_overdue"][:8]]
        lines += [f"Neu geschlossen: {len(ch['newly_closed'])}"] + [f"   • {t.department} – {t.name}" for t in ch["newly_closed"][:8]]
        lines += [f"Neu hinzugekommen: {len(ch['added'])}"] + [f"   • {t.department} – {t.name}" for t in ch["added"][:6]]
        _textbox(s, "\n".join(lines), Inches(0.6), Inches(1.3), Inches(12), Inches(5.8), 12)

    for slide in prs.slides:
        _textbox(slide, f"{config.REPORT_AUTHOR} · {config.REPORT_TITLE} · {review.header}",
                 Inches(0.4), SLIDE_H - Inches(0.45), Inches(10), Inches(0.35), 9, color="888888")
    prs.save(str(path))
    return path


def _title(slide, text: str) -> None:
    _textbox(slide, text, Inches(0.5), Inches(0.35), Inches(12.3), Inches(0.8), 26, bold=True)
    line = slide.shapes.add_shape(1, Inches(0.5), Inches(1.1), Inches(12.3), Emu(19050))
    line.fill.solid()
    line.fill.fore_color.rgb = RGBColor(0x1F, 0x77, 0xB4)
    line.line.fill.background()


def _textbox(slide, text: str, x, y, w, h, size: int, bold: bool = False, color: str = "222222"):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    for i, line in enumerate(text.split("\n")):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.font.size = Pt(size)
        p.font.bold = bold
        p.font.color.rgb = RGBColor.from_string(color)
    return tb


def _picture(slide, png: bytes, x, y, w):
    import io
    slide.shapes.add_picture(io.BytesIO(png), x, y, width=w)


def _table(slide, rows: list[list[str]], x, y, w, col_inches: list[float], font: int = 14):
    shape = slide.shapes.add_table(len(rows), len(rows[0]), x, y, w, Inches(0.4) * len(rows))
    tbl = shape.table
    for i, ci in enumerate(col_inches):
        tbl.columns[i].width = Inches(ci)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            cell = tbl.cell(r, c)
            cell.text = str(val)
            for p in cell.text_frame.paragraphs:
                p.font.size = Pt(font)
                p.font.bold = r == 0
                if r > 0 and c == len(row) - 1 and str(val).startswith("▲"):
                    p.font.color.rgb = RGBColor(0xD6, 0x27, 0x28)
                elif r > 0 and c == len(row) - 1 and str(val).startswith("▼"):
                    p.font.color.rgb = RGBColor(0x2C, 0xA0, 0x2C)
    return shape


def _color_table_cell(tbl, r: int, c: int, hex_color: str) -> None:
    for p in tbl.cell(r, c).text_frame.paragraphs:
        p.font.color.rgb = RGBColor.from_string(hex_color.lstrip("#"))
