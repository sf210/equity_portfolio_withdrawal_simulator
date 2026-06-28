# `data/` — broad developed-market return data (not committed)

The `global` equity-return sample is built from the **Jordà-Schularick-Taylor
Macrohistory Database** ([macrohistory.net](https://www.macrohistory.net/database)).
That dataset is licensed **CC BY-NC-SA 4.0**, so it is **not redistributed in
this repository**. Instead you generate the derived file locally:

```bash
# Needs pandas (the runtime does not). Use a venv that has it, e.g.:
~/finance/planning/.venv/bin/python fetch_global_data.py
# -> writes data/global_returns.csv
```

This downloads the JST Stata file and writes `data/global_returns.csv` with one
row per country-year:

```
country,year,eq_pct,infl_pct
```

`global_market_data.py` reads that CSV at runtime (no pandas needed). Until it
exists, the `global` model raises a clear error and the `us` model is unaffected.

Override the location with the `MC_GLOBAL_DATA` environment variable.

## Attribution (required by the JST license)

If you use the `global` model, cite:

- Òscar Jordà, Katharina Knoll, Dmitry Kuvshinov, Moritz Schularick, and Alan M.
  Taylor. 2019. *The Rate of Return on Everything, 1870–2015.* (returns data)
- Òscar Jordà, Moritz Schularick, and Alan M. Taylor. 2017. *Macrofinancial
  History and the New Business Cycle Facts.* (general)

The data is for non-commercial use under CC BY-NC-SA 4.0.
