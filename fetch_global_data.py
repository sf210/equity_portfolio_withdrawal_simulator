#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""One-time fetcher for the broad developed-market return data.

Downloads the Jordà-Schularick-Taylor Macrohistory Database (Stata file) and
derives `data/global_returns.csv`: per-country (nominal equity total return, CPI
inflation) year-pairs that `global_market_data.py` reads at runtime.

The JST data is licensed CC BY-NC-SA 4.0 and is NOT redistributed in this repo;
this script reproduces the derived file locally. Cite, per the JST terms:
  - Jordà, Knoll, Kuvshinov, Schularick & Taylor (2019), "The Rate of Return on
    Everything, 1870-2015" (returns), and
  - Jordà, Schularick & Taylor (2017), "Macrofinancial History and the New
    Business Cycle Facts" (general).

Requires pandas (only this setup step does -- the runtime does not). Use a venv
that has it, e.g.:
    ~/finance/planning/.venv/bin/python fetch_global_data.py
Or point it at an already-downloaded .dta:
    python fetch_global_data.py --dta /path/to/JSTdatasetR6.dta
"""

from __future__ import annotations

import argparse
import pathlib
import tempfile
import urllib.request

import pandas as pd

JST_DTA_URL = ("https://www.macrohistory.net/app/download/9834512469/"
               "JSTdatasetR6.dta?t=1763503850")

_HERE = pathlib.Path(__file__).resolve().parent
OUT_PATH = _HERE / "data" / "global_returns.csv"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dta", default=None,
                    help="path to a local JSTdatasetR6.dta (skip the download)")
    ap.add_argument("-o", "--output", default=str(OUT_PATH),
                    help=f"output CSV (default {OUT_PATH})")
    args = ap.parse_args()

    if args.dta:
        dta_path = args.dta
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".dta", delete=False)
        tmp.close()
        print(f"Downloading JST Macrohistory Database...\n  {JST_DTA_URL}")
        urllib.request.urlretrieve(JST_DTA_URL, tmp.name)
        dta_path = tmp.name

    df = pd.read_stata(dta_path).sort_values(["country", "year"])

    # Per country: inflation = year-over-year change in the CPI index; equity is
    # the nominal total return. Keep only rows with both (drops each country's
    # first year, which has no inflation, and any country lacking equity data).
    df["infl"] = df.groupby("country")["cpi"].pct_change()
    keep = df.dropna(subset=["eq_tr", "infl"])

    out = pathlib.Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    with open(out, "w", newline="") as f:
        f.write("country,year,eq_pct,infl_pct\n")
        for _, r in keep.iterrows():
            f.write(f"{r['country']},{int(r['year'])},"
                    f"{100.0 * r['eq_tr']:.6f},{100.0 * r['infl']:.6f}\n")
            rows += 1

    n_countries = keep["country"].nunique()
    print(f"Wrote {rows} rows for {n_countries} countries "
          f"({int(keep['year'].min())}-{int(keep['year'].max())}) to {out}")


if __name__ == "__main__":
    main()
