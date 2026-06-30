# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Matplotlib figures for the web report, rendered to base64 PNGs.

Everything is in **real (today's-dollar)** terms. The fan charts use the same
green-above / red-below shaded-percentile style as the desktop PDF report, with
the percentile bands the web UI asks for (1/5/25/50/75/95/99). Imported lazily by
app.py only when a report is rendered, so matplotlib stays off the import path
for the rest of the app.
"""

from __future__ import annotations

import base64
import io

import numpy as np
import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["text.parse_math"] = False

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

# Percentiles shown, worst tail -> best.
PCTS = [1, 5, 25, 50, 75, 95, 99]

# Bands as (inner, outer) percentile pairs, nearest the median first.
_UPPER = [(50, 75), (75, 95), (95, 99)]
_LOWER = [(50, 25), (25, 5), (5, 1)]
_GREENS = ["#a5d6a7", "#66bb6a", "#2e7d32"]   # light -> dark, above median
_REDS = ["#ef9a9a", "#e57373", "#c62828"]     # light -> dark, below median

_BAR = "#5b8def"
_GRID = "#e6e6e6"


def _ord(p: int) -> str:
    return "1st" if p == 1 else f"{p}th"  # our percentiles only need this case


def _money(v: float, _pos=None) -> str:
    a = abs(v)
    if a >= 1e6:
        return f"${v / 1e6:,.1f}M"
    if a >= 1e3:
        return f"${v / 1e3:,.0f}k"
    return f"${v:,.0f}"


def _pct(v: float, _pos=None) -> str:
    return f"{v:.0f}%"


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _fan(ax, series, title, *, symlog=False, amount=None):
    """Shaded-percentile fan of a (sims, years) array onto `ax`."""
    years = series.shape[1]
    x = np.arange(1, years + 1)
    q = {p: np.percentile(series, p, axis=0) for p in PCTS}

    for (inner, outer), color in zip(_UPPER, _GREENS):
        ax.fill_between(x, q[inner], q[outer], color=color, linewidth=0)
    for (inner, outer), color in zip(_LOWER, _REDS):
        ax.fill_between(x, q[outer], q[inner], color=color, linewidth=0)
    ax.plot(x, q[50], color="black", lw=1.6, label="median")
    if amount is not None:
        ax.axhline(amount, color="#555555", lw=1.0, ls="--", label="starting amount")

    ax.set_title(title, fontsize=12, loc="left")
    ax.set_xlabel("Year")
    ax.set_xlim(1, years)
    ax.margins(x=0)
    if symlog:
        linthresh = max(1_000.0, (amount or 1_000) / 100.0)
        ax.set_yscale("symlog", linthresh=linthresh)
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_formatter(FuncFormatter(_money))
    ax.grid(True, axis="y", color=_GRID, lw=0.6)

    # Legend keyed to the band edges (outer percentiles), best -> worst.
    from matplotlib.patches import Patch
    handles = [plt.Line2D([], [], color="black", lw=1.6, label="median")]
    for (_i, outer), color in zip(reversed(_UPPER), reversed(_GREENS)):
        handles.append(Patch(color=color, label=f"{_ord(outer)} pct"))
    for (_i, outer), color in zip(_LOWER, _REDS):
        handles.append(Patch(color=color, label=f"{_ord(outer)} pct"))
    # Outside the plot (right) so it never sits on top of the shaded bands.
    ax.legend(handles=handles, loc="center left", bbox_to_anchor=(1.005, 0.5),
              fontsize=8, framealpha=0.95)


def _balance_hist(ax, values, title, amount):
    """Histogram of ending balances on a log x-axis starting at $1.

    Balances span depletion (0) to many multiples of the start. A log axis from
    $1 keeps the surviving distribution readable; the large mass of depleted
    paths (balance below $1) falls off the left edge rather than dominating with
    a spike at zero. The depletion rate is shown elsewhere (fan chart / summary).
    """
    v = np.asarray(values, dtype=float)
    vmax = max(float(v.max()), 10.0)
    bins = np.logspace(0.0, np.log10(vmax), 40)  # $1 -> max
    ax.hist(v, bins=bins, color=_BAR, edgecolor="white", linewidth=0.4)
    ax.set_xscale("log")
    ax.set_xlim(1.0, vmax)
    med = float(np.median(v))
    lbl = f"median {_money(med)}"
    if med >= 1.0:
        ax.axvline(med, color="#c62828", lw=1.4, ls="--", label=lbl)
    else:  # median below $1: most paths deplete; show the label only
        ax.plot([], [], color="#c62828", lw=1.4, ls="--", label=lbl)
    ax.set_title(title, fontsize=12, loc="left")
    ax.set_ylabel("Simulations")
    ax.xaxis.set_major_formatter(FuncFormatter(_money))
    ax.grid(True, axis="y", color=_GRID, lw=0.6)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)


def _hist(ax, values, title, *, money=True, hi_pct=None):
    # Optionally clip the x-range to a percentile so a long right tail (e.g. the
    # ending-balance distribution) doesn't squash the visible bulk.
    rng = None
    if hi_pct is not None:
        rng = (min(0.0, float(np.min(values))), float(np.percentile(values, hi_pct)))
    ax.hist(values, bins=40, range=rng, color=_BAR, edgecolor="white", linewidth=0.4)
    if rng is not None:
        ax.set_xlim(*rng)
    med = float(np.median(values))
    ax.axvline(med, color="#c62828", lw=1.4, ls="--",
               label=f"median {(_money(med) if money else _pct(med))}")
    ax.set_title(title, fontsize=12, loc="left")
    ax.set_ylabel("Simulations")
    ax.xaxis.set_major_formatter(FuncFormatter(_money if money else _pct))
    ax.grid(True, axis="y", color=_GRID, lw=0.6)
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)


def max_drawdowns(equities, inflations):
    """Per-path worst peak-to-trough real return, EXCLUDING withdrawals.

    Pure market experience: the cumulative real-return index of the equity draws,
    with no cashflows. Returns an array of (negative) max drawdowns, one per sim.
    """
    real = (1.0 + equities) / (1.0 + inflations) - 1.0
    idx = np.cumprod(1.0 + real, axis=1)
    idx = np.concatenate([np.ones((idx.shape[0], 1)), idx], axis=1)
    running_max = np.maximum.accumulate(idx, axis=1)
    dd = idx / running_max - 1.0
    return dd.min(axis=1)


def build_figures(data: dict) -> dict:
    """Return {name: data-URI PNG} for the four web-report charts."""
    figs = {}

    fig, ax = plt.subplots(figsize=(10, 4.2))
    _fan(ax, data["balances_real"],
         "Portfolio balance — today's dollars (log scale)",
         symlog=True, amount=data["amount"])
    ax.set_ylabel("Balance (today's $)")
    figs["balance"] = _png(fig)

    fig, ax = plt.subplots(figsize=(10, 4.2))
    _fan(ax, data["payouts_real"], "Annual withdrawal — today's dollars")
    ax.set_ylabel("Withdrawal (today's $)")
    # Linear axis sized to the data (99th-pct band) with clear headroom, so the
    # top band is never clipped. Determined per run, so the scale varies with the
    # inputs.
    top = float(np.percentile(data["payouts_real"], 99, axis=0).max())
    ax.set_ylim(0, top * 1.15)
    figs["cashflow"] = _png(fig)

    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    _balance_hist(ax, data["end_real"],
                  "Ending portfolio balance (today's $, log scale)",
                  data["amount"])
    ax.set_xlabel("Ending balance (today's $)")
    figs["ending_hist"] = _png(fig)

    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    dd = 100.0 * max_drawdowns(data["equities"], data["inflations"])
    _hist(ax, dd, "Maximum drawdown — market, excl. withdrawals", money=False)
    ax.set_xlabel("Worst peak-to-trough real return (%)")
    figs["drawdown_hist"] = _png(fig)

    return figs
