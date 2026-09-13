"""Diagramme (matplotlib) – werden sowohl in der Vorschau als auch im Export genutzt.

Jede Funktion zeichnet in eine übergebene ``Figure`` und gibt sie zurück, damit
GUI (FigureCanvas) und Report (PNG/PDF) dieselbe Darstellung verwenden.
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg", force=False)
from matplotlib.figure import Figure  # noqa: E402

from .metrics import OverdueTrendRow, SnapshotMetrics, TimelinePoint  # noqa: E402
from .model import TaskStatus  # noqa: E402

COLORS = {
    "monitored": "#4a4a4a",
    "planned": "#1f77b4",
    "closed": "#2ca02c",
    "overdue": "#d62728",
    "fulfilment": "#ff7f0e",
    TaskStatus.OPEN: "#1f77b4",
    TaskStatus.OPEN_OVERDUE: "#d62728",
    TaskStatus.CLOSED: "#2ca02c",
    TaskStatus.CLOSED_OVERDUE: "#9467bd",
    TaskStatus.HOLD: "#7f7f7f",
}


def _style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", alpha=0.3)


def draw_timeline(fig: Figure, points: list[TimelinePoint], title: str = "Master Timeline") -> Figure:
    fig.clear()
    ax = fig.add_subplot(111)
    labels = [p.label for p in points]
    x = range(len(points))
    ax.plot(x, [p.monitored for p in points], marker="o", color=COLORS["monitored"], label="Überwachte Aufgaben")
    ax.plot(x, [p.planned_closed for p in points], marker="s", color=COLORS["planned"], label="Geplant geschlossen")
    ax.plot(x, [p.actually_closed for p in points], marker="^", color=COLORS["closed"], label="Tatsächlich geschlossen")
    ax.bar(x, [p.overdue for p in points], width=0.4, color=COLORS["overdue"], alpha=0.75, label="Überfällig")
    for xi, p in zip(x, points):
        if p.overdue:
            ax.annotate(str(p.overdue), (xi, p.overdue), ha="center", va="bottom", fontsize=8, color=COLORS["overdue"])
    ax.set_xticks(list(x), labels)
    ax.set_ylabel("Aufgaben")
    ax.set_title(title, fontweight="bold", loc="left")
    _style(ax)

    ax2 = ax.twinx()
    # Erfüllungsgrad nur dort, wo laut Plan bereits etwas geschlossen sein sollte
    pct = [p.fulfilment_pct if p.planned_closed else float("nan") for p in points]
    ax2.plot(x, pct, marker="D", linestyle="--", color=COLORS["fulfilment"], label="Erfüllungsgrad %")
    ax2.set_ylim(0, 110)
    ax2.set_ylabel("Erfüllungsgrad [%]")
    ax2.spines["top"].set_visible(False)
    for xi, p, v in zip(x, points, pct):
        if v == v:  # nicht NaN
            ax2.annotate(f"{v:.0f}%", (xi, v), textcoords="offset points",
                         xytext=(0, 6), ha="center", fontsize=8, color=COLORS["fulfilment"])
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="center left", fontsize=8, frameon=False)
    fig.tight_layout()
    return fig


def draw_department_status(fig: Figure, m: SnapshotMetrics, title: str = "Aufgaben je Fachabteilung") -> Figure:
    """Gestapelte Balken: Open / Open Overdue / Closed / Closed Overdue / Hold je Abteilung."""
    fig.clear()
    ax = fig.add_subplot(111)
    deps = m.departments
    order = [TaskStatus.CLOSED, TaskStatus.CLOSED_OVERDUE, TaskStatus.OPEN, TaskStatus.OPEN_OVERDUE, TaskStatus.HOLD]
    bottom = [0] * len(deps)
    x = range(len(deps))
    for st in order:
        vals = [m.by_department[d].n(st) for d in deps]
        ax.bar(x, vals, bottom=bottom, color=COLORS[st], label=st.value, width=0.7)
        bottom = [b + v for b, v in zip(bottom, vals)]
    for xi, tot in zip(x, bottom):
        ax.annotate(str(tot), (xi, tot), ha="center", va="bottom", fontsize=8)
    ax.set_xticks(list(x), deps, rotation=45, ha="right")
    ax.set_ylabel("Aufgaben")
    ax.set_title(f"{title} – {m.snapshot.display_name}", fontweight="bold", loc="left")
    ax.legend(fontsize=8, frameon=False, ncol=5, loc="upper right")
    _style(ax)
    fig.tight_layout()
    return fig


def draw_overdue_by_department(fig: Figure, m: SnapshotMetrics, previous: SnapshotMetrics | None = None,
                               title: str = "Überfällige Aufgaben je Fachabteilung") -> Figure:
    fig.clear()
    ax = fig.add_subplot(111)
    cur = m.overdue_by_department()
    prev = previous.overdue_by_department() if previous else {}
    deps = sorted(set(cur) | set(prev), key=lambda d: (-cur.get(d, 0), d))
    x = list(range(len(deps)))
    w = 0.38
    if previous:
        ax.bar([i - w / 2 for i in x], [prev.get(d, 0) for d in deps], width=w, color="#bbbbbb",
               label=f"Vorwoche ({previous.snapshot.display_name.split()[0]})")
        ax.bar([i + w / 2 for i in x], [cur.get(d, 0) for d in deps], width=w, color=COLORS["overdue"],
               label=f"Aktuell ({m.snapshot.display_name.split()[0]})")
    else:
        ax.bar(x, [cur.get(d, 0) for d in deps], width=0.6, color=COLORS["overdue"], label="Überfällig")
    for i, d in enumerate(deps):
        v = cur.get(d, 0)
        if v:
            ax.annotate(str(v), (i + (w / 2 if previous else 0), v), ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x, deps, rotation=45, ha="right")
    ax.set_ylabel("Überfällige Aufgaben")
    ax.set_title(title, fontweight="bold", loc="left")
    ax.legend(fontsize=8, frameon=False)
    _style(ax)
    fig.tight_layout()
    return fig


def draw_overdue_trend_table(fig: Figure, rows: list[OverdueTrendRow], prev_label: str, cur_label: str,
                             title: str = "Top-Overdues – Vorwoche vs. Aktuell") -> Figure:
    fig.clear()
    ax = fig.add_subplot(111)
    ax.axis("off")
    ax.set_title(title, fontweight="bold", loc="left")
    if not rows:
        ax.text(0.5, 0.5, "Keine überfälligen Aufgaben", ha="center", va="center")
        return fig
    cells = [[r.department, str(r.previous), str(r.current), f"{r.arrow} {r.delta:+d}"] for r in rows]
    tbl = ax.table(cellText=cells, colLabels=["Fachabteilung", prev_label, cur_label, "Trend"],
                   loc="center", cellLoc="center", colWidths=[0.4, 0.2, 0.2, 0.2])
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
