"""One matplotlib style for every figure, so charts read as one set.

Colors are the validated default palette from the dataviz guidance:
categorical slots in fixed order, recessive hairline grid, text in ink
colors (never in the series color). Every figure gets a caption saying
what data it shows.
"""

import matplotlib

matplotlib.use("Agg")  # render to files, no window needed
import matplotlib.pyplot as plt  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]   # blue, orange, aqua (first three slots)
CRITICAL = "#d03b3b"                          # status colour: anomalies only
TYPE_COLOR = {"Retail": SERIES[0], "Office": SERIES[1]}

CAPTION = "Data: Building Data Genome Project 2 (public dataset), {year}, real meter data."


def apply():
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"], "font.size": 10,
        "text.color": INK, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
        "axes.titlesize": 12, "axes.titleweight": "semibold", "axes.titlelocation": "left",
        "axes.edgecolor": AXIS, "axes.linewidth": 1,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 1, "grid.linestyle": "-",
        "axes.axisbelow": True,
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK_2, "ytick.labelcolor": INK_2,
        "lines.linewidth": 2, "lines.solid_capstyle": "round", "lines.solid_joinstyle": "round",
        "legend.frameon": False, "legend.labelcolor": INK_2,
    })


def caption(fig, year, extra=""):
    """Data-source line placed under everything already drawn (axis labels,
    legends), so it can never collide with them."""
    text = CAPTION.format(year=year) + (" " + extra if extra else "")
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    to_fig = fig.transFigure.inverted()
    bottom = min(ax.get_tightbbox(renderer).transformed(to_fig).y0 for ax in fig.axes)
    fig.text(0.01, bottom - 0.02, text, fontsize=8, color=MUTED, ha="left", va="top")


LABEL_BOX = {"boxstyle": "square,pad=0.15", "facecolor": SURFACE, "edgecolor": "none"}


def save(fig, path):
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
