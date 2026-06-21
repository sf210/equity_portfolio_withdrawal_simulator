"""Joint model of one-year nominal equity returns and CPI inflation.

The annuity-withdrawal projection needs, for each future year, BOTH a nominal
equity return (to grow the account) and an inflation rate (to express results in
today's dollars). Because equity returns and inflation are correlated, they must
be drawn *jointly* rather than independently. Two modes are provided:

  "bootstrap"  (default) -- resample actual historical year-pairs with
                replacement (IID). Preserves the empirical distribution: fat left
                tail, skew, and the exact contemporaneous equity/inflation
                correlation. Recommended for retirement risk work (Pfau 2010:
                normal-based MC overstates safe withdrawal rates vs. bootstrap).

  "block"      -- moving/circular block bootstrap: resample consecutive runs of
                `block_length` years (default 5) and stitch them together. Unlike
                IID bootstrap it preserves *serial* correlation -- momentum and
                mean reversion, and multi-year runs of high/low inflation -- which
                widens the left tail of multi-year outcomes. Blocks wrap around
                the end of the series so every start year is equally likely.

  "lognormal"  -- fit a *bivariate* normal to (log(1+equity), log(1+inflation))
                and draw from it. Smooth and extrapolates beyond observed values,
                but has zero skew/kurtosis so it understates tail risk. The
                fitted covariance still reproduces the historical correlation.

All expose the same interface:

    model = JointReturnModel("block", block_length=5)
    equity, infl = model.sample_path(years=30, rng=np.random.default_rng(0))

returning two length-`years` numpy arrays of decimal fractions.
"""

from __future__ import annotations

import numpy as np

import market_data


class JointReturnModel:
    def __init__(self, mode: str = "bootstrap", block_length: int = 5):
        if mode not in ("bootstrap", "block", "lognormal"):
            raise ValueError(
                f"unknown mode {mode!r}; use 'bootstrap', 'block', or 'lognormal'"
            )
        if block_length < 1:
            raise ValueError("block_length must be >= 1")
        self.mode = mode
        self.block_length = block_length
        self.equity = np.asarray(market_data.equity_returns(), dtype=float)
        self.inflation = np.asarray(market_data.inflation_rates(), dtype=float)

        # Log-space stats, used by the lognormal mode and reported by summary().
        self._log = np.column_stack(
            [np.log1p(self.equity), np.log1p(self.inflation)]
        )
        self._log_mean = self._log.mean(axis=0)
        self._log_cov = np.cov(self._log, rowvar=False)

    def sample_path(self, years: int, rng: np.random.Generator):
        """Return (equity_returns, inflation_rates), each a length-`years` array."""
        n = self.equity.size
        if self.mode == "bootstrap":
            idx = rng.integers(0, n, size=years)
        elif self.mode == "block":
            # Circular block bootstrap: draw enough blocks to cover `years`, each
            # a run of `block_length` consecutive (wrap-around) historical years.
            L = self.block_length
            n_blocks = -(-years // L)  # ceil division
            starts = rng.integers(0, n, size=n_blocks)
            offsets = np.arange(L)
            idx = ((starts[:, None] + offsets[None, :]) % n).ravel()[:years]
        else:  # lognormal: bivariate-normal log-returns, converted to fractions.
            draws = rng.multivariate_normal(self._log_mean, self._log_cov, size=years)
            return np.expm1(draws[:, 0]), np.expm1(draws[:, 1])
        return self.equity[idx], self.inflation[idx]

    def summary(self) -> str:
        """Human-readable description of the calibrated distribution."""
        eq, infl = self.equity, self.inflation
        corr = np.corrcoef(eq, infl)[0, 1]
        # Geometric (compound) mean of equity over the full sample.
        geo = np.exp(np.log1p(eq).mean()) - 1
        label = self.mode
        if self.mode == "block":
            label = f"block(len={self.block_length})"
        return (
            f"model={label}  n_years={eq.size} ({market_data.YEARS[0]}-"
            f"{market_data.YEARS[-1]})\n"
            f"  equity: arith mean {eq.mean():6.2%}  geo mean {geo:6.2%}  "
            f"std {eq.std(ddof=1):6.2%}\n"
            f"  CPI   : arith mean {infl.mean():6.2%}  std {infl.std(ddof=1):6.2%}\n"
            f"  corr(equity, inflation) = {corr:+.3f}"
        )
