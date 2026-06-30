#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The single, consolidated PDF report for the annuity-equivalent Monte Carlo.

One document, in this order, from the raw per-path arrays collected by
montecarlo.build_report (the report_data dict):

  1. A summary table (page 1, top) -- in today's (real) and nominal dollars, the
     ending balance, total return (annualized geometric mean), and mean annual
     withdrawal across the 1/5/25/50/75/95/99 percentiles, with the worst real
     equity returns and a highlighted downside line. This matches webapp/app.py.
  2. The end-of-year balance fan chart (page 1, below the table): the median plus
     the 25/75, 5/95 and 1/99 percentile bands, shaded green above the median and
     red below it and darkening toward the tails so the unfavourable region draws
     the eye, on a pseudo-log (symlog) y-axis so depletion to zero is visible.
  3. A "Median and Stress Scenarios" section: for the path whose ending balance
     sits at the median, 25th, 5th, and 1st percentile, a dual-axis chart of that
     path's market return, inflation, and annuity discount rate by year, with its
     mean/min/max annual withdrawal (today's dollars) and ending balance.
  4. A paginated per-year simulation-summary table (balance percentiles + median
     withdrawal).

Matplotlib is imported here (not in montecarlo.py) so the command-line tool
stays light; callers import this module lazily only when the report is requested.
"""

from __future__ import annotations

import numpy as np
import matplotlib

matplotlib.use("Agg")  # headless: render straight to the PDF, no display needed.
# Dollar amounts appear throughout; keep "$" literal instead of entering TeX
# math mode (paired "$...$" would otherwise be parsed and italicised).
matplotlib.rcParams["text.parse_math"] = False

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Patch, Rectangle

# Percentiles shown throughout the report (mirrors webapp/app.py + figures.py).
PCTS = [1, 5, 25, 50, 75, 95, 99]
PCT_HEADERS = ["1st", "5th", "25th", "Median", "75th", "95th", "99th"]

# Percentiles needed to draw the fan bands, worst tail up to the best.
_PCTS = [1.0, 5.0, 25.0, 50.0, 75.0, 95.0, 99.0]

# Green shades for the bands above the median (light near the median, dark far);
# red shades for the bands below it. Each list runs nearest -> furthest.
_GREENS = ["#a5d6a7", "#66bb6a", "#2e7d32"]
_REDS = ["#ef9a9a", "#e57373", "#c62828"]

# Pairs of (inner, outer) percentile bounding each shaded band.
_UPPER_PAIRS = [(50.0, 75.0), (75.0, 95.0), (95.0, 99.0)]
_LOWER_PAIRS = [(50.0, 25.0), (25.0, 5.0), (5.0, 1.0)]

# The four representative scenarios: label -> ending-balance percentile.
_SCENARIOS = [
    ("Median", 50.0),
    ("25th percentile", 25.0),
    ("5th percentile", 5.0),
    ("1st percentile", 1.0),
]

def _ord(p: float) -> str:
    return "1st" if p == 1 else f"{p:g}th"  # our percentiles only need this case


def _money(v: float) -> str:
    """Compact dollar label, e.g. $1.24M / $930k / $0."""
    a = abs(v)
    if a >= 1e6:
        return f"${v / 1e6:,.2f}M"
    if a >= 1e3:
        return f"${v / 1e3:,.0f}k"
    return f"${v:,.0f}"


def _money_axis(x, _pos) -> str:
    return _money(x)


def _pcts(values: np.ndarray) -> list:
    """The PCTS percentiles of a 1-D outcome array, as plain floats."""
    return [float(np.percentile(values, p)) for p in PCTS]


def _scenario_indices(end_real: np.ndarray):
    """Pick the representative path index for each scenario percentile.

    Returns a list of (label, percentile, index, target_value); index is the
    path whose ending balance is closest to that percentile of the sample.
    """
    out = []
    for label, pct in _SCENARIOS:
        target = float(np.percentile(end_real, pct))
        idx = int(np.argmin(np.abs(end_real - target)))
        out.append((label, pct, idx, target))
    return out


# --------------------------------------------------------------------------- #
# Summary cards
# --------------------------------------------------------------------------- #

def _summary_rows(data):
    """The six summary rows (real then nominal: balance, return, withdrawal).

    Each row is (label, [seven percentile-cell strings]); money for balance and
    withdrawal, percentage for the annualized geometric-mean total return.
    """
    eq, infl = data["equities"], data["inflations"]
    n = eq.shape[1]
    total_real = np.prod((1.0 + eq) / (1.0 + infl), axis=1) ** (1.0 / n) - 1.0
    total_nom = np.prod(1.0 + eq, axis=1) ** (1.0 / n) - 1.0
    wd_real = data["payouts_real"].mean(axis=1)
    wd_nom = data["payouts_nominal"].mean(axis=1)

    def money(a):
        return [_money(v) for v in _pcts(a)]

    def pct(a):
        return [f"{v * 100:.1f}%" for v in _pcts(a)]

    return [
        ("Real — Ending balance", money(data["end_real"])),
        ("Real — Total return (geo)", pct(total_real)),
        ("Real — Mean withdrawal", money(wd_real)),
        ("Nominal — Ending balance", money(data["end_nom"])),
        ("Nominal — Total return (geo)", pct(total_nom)),
        ("Nominal — Mean withdrawal", money(wd_nom)),
    ]


def _summary_grid(fig, rect, data):
    """Draw the real/nominal percentile summary table into `rect`."""
    ax = fig.add_axes(rect)
    ax.axis("off")
    rows = _summary_rows(data)
    cell_text = [[label] + cells for label, cells in rows]
    col_labels = [""] + PCT_HEADERS

    tbl = ax.table(cellText=cell_text, colLabels=col_labels, loc="center",
                   cellLoc="right", colLoc="center")
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(8.5)
    tbl.scale(1.0, 1.5)
    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#dddddd")
        # Give the row-label column more room than the seven data columns.
        cell.set_width(0.26 if c == 0 else 0.74 / len(PCT_HEADERS))
        if r == 0:  # header row
            cell.set_facecolor("#37474f")
            cell.set_text_props(color="white", fontweight="bold")
        elif c == 0:  # row-label column: real rows green, nominal rows grey
            real = r <= 3
            cell.set_facecolor("#1b5e20" if real else "#eceff1")
            cell.set_text_props(ha="left", fontweight="bold",
                                color="white" if real else "black")
        cell.PAD = 0.03


def _downside_strip(fig, rect, text):
    """A highlighted one-line callout (the downside / depletion summary)."""
    ax = fig.add_axes(rect)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    ax.add_patch(Rectangle((0, 0), 1, 1, facecolor="#fff3e0", edgecolor="#ffcc80",
                           lw=1.0, transform=ax.transAxes, clip_on=False))
    ax.text(0.015, 0.5, text, fontsize=9.5, va="center", ha="left",
            transform=ax.transAxes, fontweight="bold", color="#5d4037")


# --------------------------------------------------------------------------- #
# Fan chart
# --------------------------------------------------------------------------- #

def _draw_fan(ax, data):
    """Render the end-of-year balance fan chart onto `ax`."""
    balances = data["balances_real"]            # (sims, years), today's dollars
    years = balances.shape[1]
    x = np.arange(1, years + 1)
    q = {p: np.percentile(balances, p, axis=0) for p in _PCTS}

    # Shade outward from the median so nearer bands draw on top of farther ones.
    for (inner, outer), color in zip(_UPPER_PAIRS, _GREENS):
        ax.fill_between(x, q[inner], q[outer], color=color, linewidth=0)
    for (inner, outer), color in zip(_LOWER_PAIRS, _REDS):
        ax.fill_between(x, q[outer], q[inner], color=color, linewidth=0)
    ax.plot(x, q[50.0], color="black", lw=1.8)
    ax.axhline(data["amount"], color="#555555", lw=1.0, ls="--")

    ax.set_title("End-of-year portfolio balance (today's dollars, log scale)",
                 fontsize=12, loc="left")
    ax.set_xlabel("Year")
    ax.set_ylabel("Balance (today's dollars)")
    ax.set_xlim(1, years)
    ax.margins(x=0)
    # Pseudo-log (symlog) y-axis: the balance can fall to zero, which a true log
    # scale cannot show, so the region below `linthresh` is linear (covering 0)
    # and everything above is logarithmic to keep the wide tail-to-tail spread
    # legible.
    linthresh = max(1_000.0, data["amount"] / 100.0)
    ax.set_yscale("symlog", linthresh=linthresh)
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(_money_axis))
    ax.grid(True, axis="y", color="#e0e0e0", lw=0.6)

    handles = [
        plt.Line2D([], [], color="black", lw=1.8, label="median"),
        plt.Line2D([], [], color="#555555", lw=1.0, ls="--",
                   label="starting amount"),
    ]
    for (inner, outer), color in zip(reversed(_UPPER_PAIRS), reversed(_GREENS)):
        handles.append(Patch(color=color, label=f"{_ord(outer)} pct"))
    for (inner, outer), color in zip(_LOWER_PAIRS, _REDS):
        handles.append(Patch(color=color, label=f"{_ord(outer)} pct"))
    ax.legend(handles=handles, loc="upper left", fontsize=8, ncol=2,
              framealpha=0.9)


def _summary_fan_page(pdf, data):
    """Page 1: title, the two summary cards + downside line, then the fan chart."""
    fig = plt.figure(figsize=(11, 8.5))

    fig.text(0.06, 0.955, data["title"], ha="left", fontsize=16,
             fontweight="bold")
    fig.text(0.06, 0.92, data["params_line"], ha="left", fontsize=9,
             family="monospace", color="#333333")

    _summary_grid(fig, [0.06, 0.60, 0.88, 0.27], data)

    worst = f"Worst 1-yr real return: {data['worst_1yr']:.1%}"
    if data["worst_5yr"] is not None:
        worst += f"     Worst 5-yr real return (cumulative): {data['worst_5yr']:.1%}"
    fig.text(0.06, 0.585, worst, ha="left", fontsize=9, color="#333333")

    _downside_strip(fig, [0.06, 0.525, 0.88, 0.045], data["downside"])

    ax = fig.add_axes([0.085, 0.075, 0.85, 0.40])
    _draw_fan(ax, data)

    fig.text(0.06, 0.02, data["footer_text"], ha="left", fontsize=7,
             color="#888888")
    pdf.savefig(fig)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# Scenario charts
# --------------------------------------------------------------------------- #

def _scenario_page(pdf, data, scenarios):
    """The median-and-stress scenario charts, two per page."""
    eq = data["equities"]
    infl = data["inflations"]
    rate = data["interests"]
    pay = data["payouts_real"]
    years = eq.shape[1]
    x = np.arange(1, years + 1)
    has_rate = not np.all(np.isnan(rate))

    for page_start in range(0, len(scenarios), 2):
        chunk = scenarios[page_start:page_start + 2]
        fig = plt.figure(figsize=(11, 8.5))
        fig.subplots_adjust(left=0.08, right=0.90, top=0.88,
                            bottom=0.08, hspace=0.55)
        if page_start == 0:
            fig.suptitle("Median and Stress Scenarios", x=0.08, y=0.96,
                         ha="left", fontsize=15, fontweight="bold")

        for slot, (label, pct, idx, target) in enumerate(chunk):
            ax = fig.add_subplot(2, 1, slot + 1)
            ax2 = ax.twinx()

            # Market return on the left axis; inflation / discount rate on right.
            ax.axhline(0, color="#cccccc", lw=0.8)
            ml, = ax.plot(x, 100 * eq[idx], color="#1f77b4", lw=1.6,
                          marker="o", ms=3, label="market return")
            il, = ax2.plot(x, 100 * infl[idx], color="#d62728", lw=1.4,
                           marker="s", ms=3, label="inflation")
            lines = [ml, il]
            if has_rate:
                rl, = ax2.plot(x, 100 * rate[idx], color="#2ca02c", lw=1.4,
                               marker="^", ms=3, label="discount rate")
                lines.append(rl)

            ax.set_title(
                f"{label} path  (ending balance {_money(data['end_real'][idx])}, "
                f"target {_money(target)})", fontsize=11, loc="left")
            ax.set_xlabel("Year")
            ax.set_ylabel("Market return (%)", color="#1f77b4")
            ax2.set_ylabel("Inflation / discount rate (%)", color="#555555")
            ax.set_xlim(1, years)
            ax.grid(True, axis="y", color="#eeeeee", lw=0.5)
            ax.legend(handles=lines, loc="upper left", fontsize=7, ncol=3,
                      framealpha=0.9)

            w = pay[idx]
            stats = (f"Annual withdrawal (today's $):  mean {_money(w.mean())}   "
                     f"min {_money(w.min())}   max {_money(w.max())}        "
                     f"Ending balance {_money(data['end_real'][idx])}")
            ax.text(0.0, -0.32, stats, transform=ax.transAxes, fontsize=8,
                    family="monospace", va="top")

        pdf.savefig(fig)
        plt.close(fig)


# --------------------------------------------------------------------------- #
# Per-year summary table
# --------------------------------------------------------------------------- #

def _table_pages(pdf, data, rows_per_page=24):
    """Final pages: per-year summary table (balance percentiles + withdrawal)."""
    balances = data["balances_real"]
    pay = data["payouts_real"]
    years = balances.shape[1]
    age = data["age"]

    header = ["Yr", "Age", "Balance\nmedian", "Balance\n25th",
              "Balance\n5th", "Withdrawal\nmedian"]
    table_rows = []
    for t in range(years):
        b = balances[:, t]
        w = pay[:, t]
        table_rows.append([
            str(t + 1), str(age + t),
            _money(np.median(b)),
            _money(np.percentile(b, 25)),
            _money(np.percentile(b, 5)),
            _money(np.median(w)),
        ])

    for page_start in range(0, len(table_rows), rows_per_page):
        chunk = table_rows[page_start:page_start + rows_per_page]
        fig = plt.figure(figsize=(11, 8.5))
        ax = fig.add_subplot(111)
        ax.axis("off")
        if page_start == 0:
            ax.set_title("Per-year simulation summary (today's dollars)",
                         fontsize=13, loc="left", pad=18)
        tbl = ax.table(cellText=chunk, colLabels=header, loc="upper center",
                       cellLoc="right", colLoc="center")
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8.5)
        tbl.scale(1.0, 1.5)
        for (r, c), cell in tbl.get_celld().items():
            cell.set_edgecolor("#dddddd")
            if r == 0:
                cell.set_facecolor("#f0f0f0")
                cell.set_text_props(fontweight="bold")
        fig.text(0.08, 0.04, data["footer_text"], ha="left", fontsize=7,
                 color="#888888")
        pdf.savefig(fig)
        plt.close(fig)


def write_report_pdf(path, data):
    """Render the full consolidated report (data = report_data) to `path`."""
    scenarios = _scenario_indices(data["end_real"])
    with PdfPages(path) as pdf:
        _summary_fan_page(pdf, data)
        _scenario_page(pdf, data, scenarios)
        _table_pages(pdf, data)
        meta = pdf.infodict()
        meta["Title"] = data.get("title", "Monte Carlo report")
        meta["Subject"] = data.get("params_line", "")
    return path
