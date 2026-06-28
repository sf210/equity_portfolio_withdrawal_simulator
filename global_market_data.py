# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Broad developed-market annual equity returns + inflation, by country.

This is the cross-country analogue of `market_data.py` (which holds only the US
series). It loads a derived CSV of per-country (nominal equity total return, CPI
inflation) year-pairs so the equity model can block-bootstrap across a broad
sample of developed markets rather than the US alone -- the US has been an ex
post outlier, and a forward-looking distribution is better drawn from many
markets (Anarkulova, Cederburg, O'Doherty & Sias 2023).

The underlying data is the **Jordà-Schularick-Taylor Macrohistory Database**
(macrohistory.net), which is licensed CC BY-NC-SA 4.0 and is therefore NOT
committed to this repository. Run `fetch_global_data.py` once to download it and
produce `data/global_returns.csv` (see data/README.md). This module only reads
that derived CSV -- it needs no pandas, just the standard library + numpy.

CSV format (percentages, mirroring market_data):
    country,year,eq_pct,infl_pct
"""

from __future__ import annotations

import csv
import os
import pathlib

import numpy as np

_HERE = pathlib.Path(__file__).resolve().parent
DEFAULT_PATH = _HERE / "data" / "global_returns.csv"


def data_path() -> pathlib.Path:
    """Where the derived per-country CSV lives (override with MC_GLOBAL_DATA)."""
    return pathlib.Path(os.environ.get("MC_GLOBAL_DATA", str(DEFAULT_PATH)))


class GlobalDataMissing(FileNotFoundError):
    """Raised when the derived global-returns CSV has not been generated yet."""


def load(min_year: int | None = None) -> dict:
    """Load the per-country return series.

    If `min_year` is given, only year-pairs from that year onward are kept (used
    by the post-WWII sample).

    Returns a dict:
      {"series": [(country, ndarray(n, 2) of [equity_frac, infl_frac]), ...],
       "year_min": int, "year_max": int, "n_countries": int, "n_obs": int}

    Series are ordered by year within each country; rows missing either value are
    dropped (so the first year of each country, which has no inflation, is gone).
    """
    path = data_path()
    if not path.exists():
        raise GlobalDataMissing(
            f"Global-returns data not found at {path}.\n"
            "Generate it once with:  python fetch_global_data.py\n"
            "(downloads the JST Macrohistory Database; see data/README.md)."
        )

    by_country: dict[str, list[tuple[int, float, float]]] = {}
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                year = int(row["year"])
                eq = float(row["eq_pct"]) / 100.0
                infl = float(row["infl_pct"]) / 100.0
            except (KeyError, ValueError):
                continue
            if min_year is not None and year < min_year:
                continue
            by_country.setdefault(row["country"], []).append((year, eq, infl))

    if not by_country:
        raise GlobalDataMissing(f"No usable rows in {path}.")

    series = []
    y_min, y_max, n_obs = 10**9, -10**9, 0
    for country in sorted(by_country):
        recs = sorted(by_country[country])
        arr = np.array([[eq, infl] for _y, eq, infl in recs], dtype=float)
        series.append((country, arr))
        y_min = min(y_min, recs[0][0])
        y_max = max(y_max, recs[-1][0])
        n_obs += len(recs)

    return {"series": series, "year_min": y_min, "year_max": y_max,
            "n_countries": len(series), "n_obs": n_obs}
