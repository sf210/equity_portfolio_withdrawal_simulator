# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Joint model of one-year nominal equity returns and CPI inflation.

The annuity-withdrawal projection needs, for each future year, BOTH a nominal
equity return (to grow the account) and an inflation rate (to express results in
today's dollars). Because equity returns and inflation are correlated, they must
be drawn *jointly* rather than independently, so a sampled year carries both.

Sampling is always a **circular block bootstrap**: resample consecutive runs of
`block_length` years (default 5) and stitch them together. Versus IID sampling
this preserves *serial* correlation -- momentum/mean reversion and multi-year
runs of high or low inflation -- which widens the left tail of multi-year
outcomes (Pfau 2010). Two data sources are offered:

  "us"      -- the US series only (S&P 500 total return + CPI, market_data.py).

  "global"  -- a broad sample of developed markets (global_market_data.py, from
               the Jordà-Schularick-Taylor Macrohistory Database). The US has
               been an ex post outlier; a forward-looking distribution is better
               drawn from many markets (Anarkulova, Cederburg, O'Doherty & Sias
               2023). Each block is drawn from a single country (countries chosen
               in proportion to their number of years), so within-country
               sequence risk is preserved while the cross-section of national
               outcomes -- including the severe ones the US never saw -- enters
               the distribution. Requires the JST-derived data file; see
               global_market_data.py / fetch_global_data.py.

Interface:

    model = JointReturnModel("global", block_length=5)
    equity, infl = model.sample_path(years=30, rng=np.random.default_rng(0))

returning two length-`years` numpy arrays of decimal fractions.
"""

from __future__ import annotations

import numpy as np

import market_data

MODES = ("us", "global")


class JointReturnModel:
    def __init__(self, mode: str = "us", block_length: int = 5):
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}; use 'us' or 'global'")
        if block_length < 1:
            raise ValueError("block_length must be >= 1")
        self.mode = mode
        self.block_length = block_length

        # `_series`: list of per-country (n, 2) arrays of [equity_frac, infl_frac].
        # The US source is just the single-country case.
        if mode == "us":
            eq = np.asarray(market_data.equity_returns(), dtype=float)
            infl = np.asarray(market_data.inflation_rates(), dtype=float)
            self._series = [np.column_stack([eq, infl])]
            self._span = f"{market_data.YEARS[0]}-{market_data.YEARS[-1]}"
            self._source = "US S&P 500 / CPI"
        else:
            import global_market_data
            gm = global_market_data.load()
            self._series = [arr for _name, arr in gm["series"]]
            self._span = f"{gm['year_min']}-{gm['year_max']}"
            self._source = (f"global developed markets, "
                            f"{gm['n_countries']} countries (JST)")

        lengths = np.array([len(a) for a in self._series], dtype=float)
        self._weights = lengths / lengths.sum()
        # Pooled observations, used only for summary() statistics.
        self._pooled = np.concatenate(self._series, axis=0)

    def sample_path(self, years: int, rng: np.random.Generator):
        """Return (equity_returns, inflation_rates), each a length-`years` array."""
        L = self.block_length
        n_blocks = -(-years // L)  # ceil division

        if len(self._series) == 1:
            # Single series: vectorised circular block bootstrap.
            arr = self._series[0]
            n = len(arr)
            starts = rng.integers(0, n, size=n_blocks)
            offsets = np.arange(L)
            idx = ((starts[:, None] + offsets[None, :]) % n).ravel()[:years]
            out = arr[idx]
        else:
            # Each block comes from one country (chosen in proportion to its
            # length), so blocks never stitch across countries.
            chosen = rng.choice(len(self._series), size=n_blocks, p=self._weights)
            offsets = np.arange(L)
            pieces = []
            for ci in chosen:
                a = self._series[ci]
                m = len(a)
                s = int(rng.integers(0, m))
                pieces.append(a[(s + offsets) % m])
            out = np.concatenate(pieces, axis=0)[:years]

        return out[:, 0], out[:, 1]

    def summary(self) -> str:
        """Human-readable description of the calibrated distribution.

        Statistics are reported in REAL terms -- (1+equity)/(1+inflation)-1 -- so
        they are comparable across countries and robust to hyperinflation years
        (e.g. Germany 1923), whose huge nominal equity/CPI figures would otherwise
        dominate the nominal moments. The simulation deflates to today's dollars,
        so the real distribution is what drives outcomes anyway.
        """
        eq = self._pooled[:, 0]
        infl = self._pooled[:, 1]
        real = (1.0 + eq) / (1.0 + infl) - 1.0
        geo = np.exp(np.log1p(real).mean()) - 1  # compound real mean
        return (
            f"model={self.mode} block(len={self.block_length})  "
            f"source={self._source}\n"
            f"  n_obs={eq.size} ({self._span})\n"
            f"  equity (real): arith mean {real.mean():6.2%}  "
            f"geo mean {geo:6.2%}  std {real.std(ddof=1):6.2%}  "
            f"min {real.min():6.1%}\n"
            f"  CPI inflation: median {np.median(infl):6.2%}"
        )
