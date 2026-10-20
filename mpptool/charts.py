"""Diagramme (matplotlib) – werden sowohl in der Vorschau als auch im Export genutzt.

Jede Funktion zeichnet in eine übergebene ``Figure`` und gibt sie zurück, damit
GUI (FigureCanvas) und Report (PNG/PDF) dieselbe Darstellung verwenden.
"""
from __future__ import annotations

import io
from collections.abc import Collection

import matplotlib

matplotlib.use("Agg", force=False)
from matplotlib.figure import Figure  # noqa: E402

from .metrics import FinishPoint, OverdueTrendRow, SnapshotMetrics, WeekPoint, week_label  # noqa: E402
from .model import TaskStatus  # noqa: E402

COLORS = {
    "monitored": "#9a9a9a",
    "planned": "#d4ac00",
    "closed": "#2ca02c",
    "overdue": "#d62728",
    "fulfilment": "#1f77b4",
    "planned_line": "#1f77b4",
    TaskStatus.OPEN: "#1f77b4",
    TaskStatus.OPEN_OVERDUE: "#d62728",
    TaskStatus.CLOSED: "#2ca02c",
    TaskStatus.CLOSED_OVERDUE: "#9467bd",
    TaskStatus.HOLD: "#7f7f7f",
    TaskStatus.CANCELLED: "#c49a00",
}

LABEL_INK = "#333333"

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(values: list[int]) -> str:
    """Kompakte Trenddarstellung als Unicode-Zeichenfolge (für Tabellen)."""
    if not values:
        return ""
    lo, hi = min(values), max(values)
    if hi == lo:
        return _SPARK_CHARS[0] * len(values)
    span = hi - lo
    return "".join(_SPARK_CHARS[round((v - lo) / span * (len(_SPARK_CHARS) - 1))] for v in values)


def _style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.3)


def _legend_below(fig: Figure, handles, labels, ncol: int | None = None, bottom: float = 0.22,
                  legend_y: float = 0.02) -> None:
    """Platziert die Legende unterhalb der Zeichenfläche statt darüber/darauf,
    damit sie sich nie mit Balken, Linien oder Beschriftungen überlappt."""
    if ncol is None:
        ncol = min(len(handles), 4)
    fig.tight_layout(rect=(0, bottom, 1, 1))
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, legend_y),
               ncol=ncol, fontsize=9, frameon=False)


def draw_master_timeline(fig: Figure, points: list[WeekPoint], title: str = "Master Timeline") -> Figure:
    """Master Timeline je KW: blaue Linie = geplant geschlossen (kumuliert, aktueller Plan,
    bis Planende), grüne Balken = tatsächlich geschlossen, graue Balken = überwacht – beide
    nur in Wochen mit Snapshot (Ist-Werte entstehen nur zum Auswertungszeitpunkt)."""
    import math

    fig.clear()
    ax = fig.add_subplot(111)
    ax.set_title(title, fontweight="bold", loc="left")
    if not points:
        ax.axis("off")
        ax.text(0.5, 0.5, "Keine Daten im gewählten Zeitraum", ha="center", va="center")
        return fig
    n = len(points)
    x = list(range(n))
    snap = [i for i, p in enumerate(points) if p.actual_closed is not None]
    w = 0.4
    ax.bar([i - w / 2 for i in snap], [points[i].monitored for i in snap], width=w,
           color=COLORS["monitored"], label="Überwachte Aufgaben", zorder=3)
    ax.bar([i + w / 2 for i in snap], [points[i].actual_closed for i in snap], width=w,
           color=COLORS["closed"], label="Tatsächlich geschlossen (Ist)", zorder=3)
    ax.plot(x, [p.planned_closed for p in points], color=COLORS["planned_line"], lw=2,
            marker="o" if n <= 30 else None, markersize=3.5, zorder=4,
            label="Geplant geschlossen (aktueller Plan, kumuliert)")

    fs = 8 if n <= 30 else 6.5
    rot = 0 if len(snap) <= 12 else 90
    for i in snap:
        ax.annotate(str(points[i].monitored), (i - w / 2, points[i].monitored), xytext=(0, 2),
                    textcoords="offset points", ha="center", va="bottom", fontsize=fs, rotation=rot,
                    color=LABEL_INK, fontweight="bold", zorder=6)
        v = points[i].actual_closed
        ax.annotate(str(v), (i + w / 2, v), xytext=(0, 2), textcoords="offset points", ha="center",
                    va="bottom", fontsize=fs, rotation=rot, color=COLORS["closed"], fontweight="bold", zorder=6)

    ev = next((i for i, p in enumerate(points) if p.is_evaluation_week), None)
    top = max([p.planned_closed for p in points] + [points[i].monitored or 0 for i in snap] + [1])
    if ev is not None:
        ax.axvline(ev, color="#555555", ls="--", lw=1, zorder=2)
        ax.annotate(f"Auswertung {points[ev].label}", (ev, top * 1.12), xytext=(4, 0), textcoords="offset points",
                    fontsize=8, color="#555555", va="top")

    # Planlinie: jede Woche mit echtem Informationsgehalt beschriften (Anfang, Ende,
    # Snapshot-/Auswertungswochen sowie jede Änderung ggü. der Vorwoche) – eine lange
    # Kette identischer Wochenwerte zwischen zwei Terminänderungen nur mit der immer
    # gleichen Zahl zu bekleben, wäre reiner Ziffernspam ohne Zusatzinformation.
    plan_label_idx = {0, n - 1, *snap}
    if ev is not None:
        plan_label_idx.add(ev)
    plan_label_idx |= {i for i in range(1, n) if points[i].planned_closed != points[i - 1].planned_closed}
    line_fs = 8 if len(plan_label_idx) <= 30 else 6.5
    line_rot = 0 if len(plan_label_idx) <= 12 else 90
    for i in sorted(plan_label_idx):
        v = points[i].planned_closed
        ax.annotate(str(v), (i, v), xytext=(0, 6), textcoords="offset points", ha="center", va="bottom",
                    fontsize=line_fs, rotation=line_rot, color=COLORS["planned_line"], fontweight="bold", zorder=6)

    step = max(1, math.ceil(n / 26))
    ticks = list(range(0, n, step))
    labels, last_year = [], None
    for i in ticks:
        y = points[i].start.isocalendar()[0]
        labels.append(points[i].label + (f"\n{y}" if y != last_year else ""))
        last_year = y
    ax.set_xticks(ticks, labels, fontsize=8)
    ax.set_xlim(-0.7, n - 0.3)
    ax.set_ylim(0, top * 1.18)
    ax.set_ylabel("Anzahl Aufgaben")
    _style(ax)
    h, l = ax.get_legend_handles_labels()
    _legend_below(fig, h, l, ncol=3, bottom=0.2, legend_y=0.07)

    p = points[ev] if ev is not None else (points[snap[-1]] if snap else None)
    if p is not None:
        status = f"{week_label(p.start, True)}: geplant geschlossen (aktueller Plan) {p.planned_closed}"
        if p.actual_closed is not None:
            status += (f"  ·  tatsächlich geschlossen {p.actual_closed}  ·  überwacht {p.monitored}"
                       f"  ·  Erfüllungsgrad (aktueller Plan) {p.fulfilment_pct:.0f} %")
        status += f"  ·  Zeitraumende {week_label(points[-1].start, True)}: {points[-1].planned_closed} geplant geschlossen"
        fig.text(0.5, 0.015, status, ha="center", va="bottom", fontsize=8.5, color=LABEL_INK)
    return fig


def draw_finish_trend(fig: Figure, points: list[FinishPoint],
                      title: str = "Verschiebung des erwarteten Projektendes") -> Figure:
    """Erwartetes Projektende je Snapshot (Linie) mit Basisplan-Ende als Referenz;
    an jedem Punkt Datum und Verschiebung zum vorherigen Stand in Tagen."""
    import matplotlib.dates as mdates

    fig.clear()
    ax = fig.add_subplot(111)
    ax.set_title(title, fontweight="bold", loc="left")
    pts = [p for p in points if p.expected_finish]
    if not pts:
        ax.axis("off")
        ax.text(0.5, 0.5, "Kein geplantes Ende in den Daten", ha="center", va="center")
        return fig
    x = list(range(len(pts)))
    n = len(pts)
    fs = max(6.5, min(8.5, 8.5 - max(0, n - 12) * 0.1))
    exp = [mdates.date2num(p.expected_finish) for p in pts]
    ax.plot(x, exp, marker="o", color=COLORS["overdue"], lw=2, zorder=4, label="Erwartetes Projektende")
    base = [mdates.date2num(p.baseline_finish) if p.baseline_finish else float("nan") for p in pts]
    if any(p.baseline_finish for p in pts):
        ax.plot(x, base, ls="--", color=COLORS["monitored"], lw=1.5, zorder=3, label="Basisplan-Ende")

    prev = None
    for xi, p in zip(x, pts):
        txt = p.expected_finish.strftime("%d.%m.%y")
        if prev is not None:
            delta = (p.expected_finish - prev).days
            if delta:
                txt += f"\n{delta:+d} d"
        ax.annotate(txt, (xi, mdates.date2num(p.expected_finish)), xytext=(0, 7), textcoords="offset points",
                    ha="center", va="bottom", fontsize=fs, color=LABEL_INK, zorder=6)
        prev = p.expected_finish

    lo = min([*exp, *[b for b in base if b == b]])
    hi = max([*exp, *[b for b in base if b == b]])
    pad = max(14.0, (hi - lo) * 0.25)
    ax.set_ylim(lo - pad * 0.4, hi + pad)
    ax.yaxis.set_major_formatter(mdates.DateFormatter("%d.%m.%y"))
    ax.set_xticks(x, [p.label for p in pts], rotation=0 if n <= 8 else (45 if n <= 20 else 90), fontsize=9)
    ax.set_xlim(-0.5, n - 0.5)
    ax.set_ylabel("Projektende")
    _style(ax)

    first, last = pts[0], pts[-1]
    status = (f"Stand {last.label}: erwartetes Ende {last.expected_finish.strftime('%d.%m.%Y')}  ·  "
              f"Verschiebung seit {first.label}: {(last.expected_finish - first.expected_finish).days:+d} Tage")
    if last.slip_vs_baseline is not None:
        status += f"  ·  ggü. Basisplan: {last.slip_vs_baseline:+d} Tage"
    h, l = ax.get_legend_handles_labels()
    _legend_below(fig, h, l, ncol=2, bottom=0.18, legend_y=0.06)
    fig.text(0.5, 0.015, status, ha="center", va="bottom", fontsize=8.5, color=LABEL_INK)
    return fig


def draw_department_status(fig: Figure, m: SnapshotMetrics, title: str = "Aufgaben je Fachabteilung",
                           departments: Collection[str] | None = None) -> Figure:
    """Gestapelte Balken: Open / Open Overdue / Closed / Closed Overdue / Hold je Abteilung.
    ``departments`` beschränkt auf die ausgewählten Gruppen (None = alle)."""
    fig.clear()
    ax = fig.add_subplot(111)
    deps = [d for d in m.departments if departments is None or d in departments]
    order = [TaskStatus.CLOSED, TaskStatus.CLOSED_OVERDUE, TaskStatus.OPEN, TaskStatus.OPEN_OVERDUE,
             TaskStatus.HOLD, TaskStatus.CANCELLED]
    bottom = [0] * len(deps)
    x = range(len(deps))
    for st in order:
        vals = [m.by_department[d].n(st) for d in deps]
        ax.bar(x, vals, bottom=bottom, color=COLORS[st], label=st.value, width=0.7)
        bottom = [b + v for b, v in zip(bottom, vals)]
    for xi, tot in zip(x, bottom):
        if tot:
            ax.annotate(str(tot), (xi, tot), xytext=(0, 2), textcoords="offset points",
                        ha="center", va="bottom", fontsize=8, color=LABEL_INK)
    ax.set_xticks(list(x), deps, rotation=45, ha="right")
    ax.set_ylabel("Aufgaben")
    ax.set_title(f"{title} – Stand {m.as_of.isoformat()}", fontweight="bold", loc="left")
    ax.set_ylim(0, max(bottom, default=0) * 1.15 or 1)
    _style(ax)
    h, l = ax.get_legend_handles_labels()
    _legend_below(fig, h, l, ncol=3)
    return fig


def draw_overdue_by_department(fig: Figure, m: SnapshotMetrics, previous: SnapshotMetrics | None = None,
                               title: str = "Überfällige Aufgaben je Fachabteilung",
                               departments: Collection[str] | None = None) -> Figure:
    fig.clear()
    ax = fig.add_subplot(111)

    def pick(d: dict[str, int]) -> dict[str, int]:
        return {k: v for k, v in d.items() if departments is None or k in departments}

    cur = pick(m.overdue_by_department())
    prev = pick(previous.overdue_by_department()) if previous else {}
    deps = sorted(set(cur) | set(prev), key=lambda d: (-cur.get(d, 0), d))
    x = list(range(len(deps)))
    w = 0.38
    if previous:
        ax.bar([i - w / 2 for i in x], [prev.get(d, 0) for d in deps], width=w, color="#bbbbbb",
               label=f"Letzter Stichtag ({previous.as_of.isoformat()})")
        ax.bar([i + w / 2 for i in x], [cur.get(d, 0) for d in deps], width=w, color=COLORS["overdue"],
               label=f"Aktuell ({m.as_of.isoformat()})")
    else:
        ax.bar(x, [cur.get(d, 0) for d in deps], width=0.6, color=COLORS["overdue"], label="Überfällig")
    if previous:
        for i, d in enumerate(deps):
            pv = prev.get(d, 0)
            if pv:
                ax.annotate(str(pv), (i - w / 2, pv), xytext=(0, 2), textcoords="offset points",
                            ha="center", va="bottom", fontsize=8, color=LABEL_INK)
    for i, d in enumerate(deps):
        v = cur.get(d, 0)
        if v:
            ax.annotate(str(v), (i + (w / 2 if previous else 0), v), xytext=(0, 2), textcoords="offset points",
                        ha="center", va="bottom", fontsize=8, color=LABEL_INK)
    ax.set_xticks(x, deps, rotation=45, ha="right")
    ax.set_ylabel("Überfällige Aufgaben")
    ax.set_title(title, fontweight="bold", loc="left")
    top = max([*cur.values(), *prev.values()], default=0)
    ax.set_ylim(0, top * 1.15 or 1)
    _style(ax)
    h, l = ax.get_legend_handles_labels()
    _legend_below(fig, h, l, ncol=2)
    return fig


def draw_overdue_trend_table(fig: Figure, rows: list[OverdueTrendRow], prev_label: str, cur_label: str,
                             title: str = "Top-Overdues mit Trendanalyse – Letzter Stichtag vs. Aktuell") -> Figure:
    fig.clear()
    ax = fig.add_subplot(111)
    ax.axis("off")
    ax.set_title(title, fontweight="bold", loc="left")
    if not rows:
        ax.text(0.5, 0.5, "Keine überfälligen Aufgaben", ha="center", va="center")
        return fig
    cells = [[r.department, str(r.previous), str(r.current), f"{r.arrow} {r.delta:+d}", sparkline(r.history)]
             for r in rows]
    tbl = ax.table(cellText=cells, colLabels=["Fachabteilung", prev_label, cur_label, "Trend", "Verlauf"],
                   loc="center", cellLoc="center", colWidths=[0.32, 0.16, 0.16, 0.16, 0.2])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(10)
    tbl.scale(1, 1.6)
    for (r, c), cell in tbl.get_celld().items():
        if r == 0:
            cell.set_facecolor("#dddddd")
            cell.set_text_props(fontweight="bold")
        elif c == 3:
            d = rows[r - 1].delta
            cell.set_text_props(color=COLORS["overdue"] if d > 0 else (COLORS["closed"] if d < 0 else "#555555"))
    return fig


def figure_to_png(fig: Figure, dpi: int = 150) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    return buf.getvalue()
