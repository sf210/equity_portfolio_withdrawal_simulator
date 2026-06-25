# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Dynamic annuity discount rate: a lagged error-correction model on inflation.

The annuity payout depends on a discount/interest rate. Rather than fix that rate,
the dynamic mode links it to inflation through the empirical relationship between
the 10-year Treasury yield and inflation. Nominal yields and inflation are
persistent, correlated time series, so the rate is modelled as a partial
adjustment toward a long-run Fisher target driven by *lagged* inflation:

    i*_t = a + b * pi_{t-1}                         (long-run Fisher target)
    i_t  = (1 - lam) * i_{t-1} + lam * i*_t + eps_t  (error correction)

`a` is the real-rate intercept, `b` the long-run inflation pass-through, and
`lam` the annual adjustment speed. A small `lam` makes the rate sluggish: when
inflation jumps, the rate lags and the *implied real rate* (i - pi) compresses
and can go temporarily negative -- the behaviour actually observed in 2021-2022
(the Mundell-Tobin / short-run "Fisher puzzle" effect), while the long-run real
rate stays near `a`.

The reduced form `i_t = c + rho * i_{t-1} + delta * pi_{t-1} + eps_t` is fit by
OLS to historical 10-year Treasury yields (FRED GS10, annual averages) and CPI
inflation (see market_data.py), and mapped to the structural parameters via

    lam = 1 - rho,   a = c / lam,   b = delta / lam.

fit_interest_model() reproduces that regression (and reports standard errors,
t-statistics, R^2 and a Durbin-Watson statistic); the package defaults below are
those fitted values, so the model and its documentation stay in sync.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import market_data

# Starting ("today's") 10-year yield the simulated rate path begins from; the
# 2025 annual-average GS10 was 4.29%, so 4.3% is a representative current level.
DEFAULT_INITIAL_RATE = 0.043
RATE_FLOOR = 0.0  # nominal yields are floored at zero (no negative discount rate)


@dataclass
class InterestFit:
    """OLS fit of the reduced-form rate equation and its structural mapping."""
    n: int
    years: tuple[int, int]
    coef: dict[str, float]    # const, i_lag, pi_lag
    se: dict[str, float]
    tstat: dict[str, float]
    r2: float
    adj_r2: float
    sigma: float              # residual standard deviation (innovation sigma)
    dw: float                 # Durbin-Watson statistic
    a: float                  # structural: real-rate intercept
    b: float                  # structural: long-run inflation pass-through
    lam: float                # structural: annual adjustment speed


def fit_interest_model() -> InterestFit:
    """Fit i_t = c + rho*i_{t-1} + delta*pi_{t-1} + eps by OLS on the GS10 data."""
    years, i_t, i_lag, pi_lag = market_data.treasury_10y_regression_data()
    y = np.asarray(i_t, dtype=float)
    X = np.column_stack([np.ones(len(y)), np.asarray(i_lag), np.asarray(pi_lag)])
    n, k = X.shape
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = n - k
    s2 = float(resid @ resid / dof)
    cov = s2 * np.linalg.inv(X.T @ X)
    se = np.sqrt(np.diag(cov))
    sst = float(((y - y.mean()) ** 2).sum())
    sse = float((resid ** 2).sum())
    r2 = 1.0 - sse / sst
    adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / dof
    dw = float(np.sum(np.diff(resid) ** 2) / np.sum(resid ** 2))
    c, rho, delta = beta
    lam = 1.0 - rho
    names = ("const", "i_lag", "pi_lag")
    return InterestFit(
        n=n, years=(years[0], years[-1]),
        coef=dict(zip(names, beta)),
        se=dict(zip(names, se)),
        tstat=dict(zip(names, beta / se)),
        r2=r2, adj_r2=adj_r2, sigma=float(np.sqrt(s2)), dw=dw,
        a=float(c / lam), b=float(delta / lam), lam=float(lam),
    )


# Fitted defaults (computed once at import, from the in-repo data) so the
# simulator and the methodology document always agree on the parameters.
_FIT = fit_interest_model()
DEFAULT_REAL_INTERCEPT = _FIT.a    # a  (~1.7%)
DEFAULT_INFLATION_BETA = _FIT.b    # b  (~1.13)
DEFAULT_ADJUST_SPEED = _FIT.lam    # lambda (~0.17)
DEFAULT_RATE_SIGMA = _FIT.sigma    # sigma (~0.8%)


class InterestRateModel:
    """Simulate an annual annuity discount-rate path via lagged error correction.

        i*_t = a + b * pi_{t-1}
        i_t  = (1 - lam) * i_{t-1} + lam * i*_t + eps_t,   eps_t ~ N(0, sigma^2)

    The first year is priced at `initial_rate` (today's rate); thereafter the
    rate partially adjusts toward the Fisher target set by the *previous* year's
    inflation. Rates are floored at `floor` (default 0). Set stochastic=False for
    a deterministic (shock-free) path.
    """

    def __init__(self, a: float = DEFAULT_REAL_INTERCEPT,
                 b: float = DEFAULT_INFLATION_BETA,
                 lam: float = DEFAULT_ADJUST_SPEED,
                 sigma: float = DEFAULT_RATE_SIGMA,
                 initial_rate: float = DEFAULT_INITIAL_RATE,
                 floor: float = RATE_FLOOR, stochastic: bool = True):
        self.a = a
        self.b = b
        self.lam = lam
        self.sigma = sigma
        self.initial_rate = initial_rate
        self.floor = floor
        self.stochastic = stochastic

    def sample_path(self, inflation_path, rng) -> np.ndarray:
        """Return a length-N discount-rate path given a length-N inflation path.

        inflation_path[t] is year t's inflation; the rate in year t reacts to
        inflation_path[t-1] (lagged). Year 0 is the initial rate.
        """
        infl = np.asarray(inflation_path, dtype=float)
        n = infl.size
        out = np.empty(n)
        prev = self.initial_rate
        for t in range(n):
            if t == 0:
                rate = prev
            else:
                target = self.a + self.b * infl[t - 1]
                rate = (1.0 - self.lam) * prev + self.lam * target
                if self.stochastic:
                    rate += self.sigma * rng.standard_normal()
            rate = max(rate, self.floor)
            out[t] = rate
            prev = rate
        return out

    def steady_state_rate(self, inflation: float) -> float:
        """Long-run rate the process settles to at a constant inflation rate."""
        return self.a + self.b * inflation
