#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Fit and document the dynamic annuity-rate (error-correction) model.

This runs the OLS fit of the interest-rate equation on the in-repo historical
data and reports it. The regression itself lives in
``rate_model.fit_interest_model()`` (the single source of truth, whose fitted
values are also baked into rate_model.py as the simulator's defaults); this
script formats that fit as a human report and as the fit-documentation source.

Model (lagged error correction toward a long-run Fisher target):

    i*_t = a + b * pi_{t-1}
    i_t  = (1 - lam) * i_{t-1} + lam * i*_t + eps_t,   eps_t ~ N(0, sigma^2)

fit by OLS in reduced form ``i_t = c + rho*i_{t-1} + delta*pi_{t-1} + eps`` on
the 10-year Treasury yield (FRED GS10, annual averages) and CPI inflation
(market_data.py), then mapped to the structural parameters via
``lam = 1 - rho, a = c/lam, b = delta/lam``.

Usage:
    python fit_rate_model.py              # print the fit report (text)
    python fit_rate_model.py --markdown   # (re)write FIT.md, the fit document
"""

from __future__ import annotations

import argparse
import os

import rate_model

_HERE = os.path.dirname(os.path.abspath(__file__))


def text_report(f: rate_model.InterestFit) -> str:
    """A plain-text regression report for the fitted model."""
    y0, y1 = f.years
    lines = [
        "Dynamic annuity-rate model -- OLS fit",
        f"  sample      : {y0}-{y1}  (n = {f.n} annual observations)",
        "  data        : 10-yr Treasury yield (FRED GS10, annual avg)"
        " on CPI inflation",
        "",
        "Reduced form:  i_t = c + rho*i_{t-1} + delta*pi_{t-1} + eps_t",
        f"  {'term':<16}{'coef':>12}{'std err':>12}{'t':>9}",
        "  " + "-" * 49,
    ]
    labels = {"const": "c (const)", "i_lag": "rho i_{t-1}", "pi_lag": "delta pi_{t-1}"}
    for k in ("const", "i_lag", "pi_lag"):
        lines.append(f"  {labels[k]:<16}{f.coef[k]:>12.5f}"
                     f"{f.se[k]:>12.5f}{f.tstat[k]:>9.2f}")
    lines += [
        "",
        f"  R^2 = {f.r2:.4f}    adj R^2 = {f.adj_r2:.4f}    "
        f"resid sigma = {f.sigma:.5f} ({f.sigma:.2%})",
        f"  Durbin-Watson = {f.dw:.3f}",
        "",
        "Structural (error-correction) parameters:",
        f"  lambda  adjustment speed       = {f.lam:.4f}",
        f"  a       real-rate intercept    = {f.a:.5f}  ({f.a:.2%})",
        f"  b       inflation pass-through = {f.b:.4f}",
        f"  sigma   annual rate shock      = {f.sigma:.5f}  ({f.sigma:.2%})",
        "",
        f"  steady-state rate at 2.5% inflation: a + b*0.025 = "
        f"{f.a + f.b * 0.025:.2%}",
        f"  initial (today's) rate the sim starts from        : "
        f"{rate_model.DEFAULT_INITIAL_RATE:.2%}",
    ]
    return "\n".join(lines)


def markdown_report(f: rate_model.InterestFit) -> str:
    """The full fit-documentation source (FIT.md)."""
    y0, y1 = f.years
    c = f.coef
    se = f.se
    t = f.tstat
    steady = f.a + f.b * 0.025
    long_run_real = f.a + (f.b - 1.0) * 0.025
    return f"""# Dynamic Annuity-Rate Model -- Fit Report

*Empirical fit of the interest-rate process used by the dynamic Monte Carlo
mode. Regenerate with `python fit_rate_model.py --markdown`.*

## 1. Purpose

In the dynamic simulation mode the annuity discount rate is not fixed; it evolves
with inflation through the empirical link between the **10-year Treasury yield**
and **inflation**. Both are persistent, correlated time series, so the rate is a
partial adjustment toward a long-run Fisher target driven by *lagged* inflation:

```
i*_t = a + b * pi_(t-1)                              (long-run Fisher target)
i_t  = (1 - lam) * i_(t-1) + lam * i*_t + eps_t       (error correction)
```

`a` is the real-rate intercept, `b` the long-run inflation pass-through, and
`lam` the annual adjustment speed; `eps_t ~ N(0, sigma^2)`.

## 2. Data and sample

| | |
|---|---|
| Dependent variable | 10-year Treasury constant-maturity yield, annual average of monthly **FRED GS10** [1] |
| Inflation regressor | CPI-U annual-average inflation (BLS, via usinflationcalculator.com) [2] |
| Sample | **{y0}-{y1}** (n = **{f.n}** annual observations) |
| Estimation | Ordinary least squares (reduced form), `numpy.linalg.lstsq` |

GS10 begins in 1953; the lagged regressors drop the first year, so estimation
starts in {y0}. The yield series lives in `market_data.py`
(`treasury_10y_regression_data()`); the regression is `rate_model.fit_interest_model()`.

## 3. Reduced-form regression

`i_t = c + rho * i_(t-1) + delta * pi_(t-1) + eps_t`

| term | coef | std err | t |
|---|---:|---:|---:|
| c (intercept) | {c['const']:.5f} | {se['const']:.5f} | {t['const']:.2f} |
| rho &middot; i_(t-1) | {c['i_lag']:.5f} | {se['i_lag']:.5f} | {t['i_lag']:.2f} |
| delta &middot; pi_(t-1) | {c['pi_lag']:.5f} | {se['pi_lag']:.5f} | {t['pi_lag']:.2f} |

R&sup2; = **{f.r2:.4f}**, adjusted R&sup2; = {f.adj_r2:.4f}, residual sigma =
**{f.sigma:.5f} ({f.sigma:.2%})**, Durbin-Watson = **{f.dw:.3f}**.

The high `rho` ({c['i_lag']:.3f}, t = {t['i_lag']:.1f}) confirms the strong
persistence of yields; the significant `delta` ({c['pi_lag']:.3f}, t =
{t['pi_lag']:.1f}) is the inflation pass-through. The Durbin-Watson near 2 means
the residuals show little remaining first-order autocorrelation, so the AR(1)-in-
levels specification is adequate. The intercept `c` is not individually
significant (t = {t['const']:.2f}), which is expected -- the long-run real rate is
weakly identified separately from the persistence term.

## 4. Structural parameters

Mapping `lam = 1 - rho`, `a = c / lam`, `b = delta / lam`, with `sigma` the
residual standard deviation:

| parameter | symbol | value |
|---|---|---:|
| adjustment speed | lam | **{f.lam:.4f}** |
| real-rate intercept | a | **{f.a:.5f}  ({f.a:.2%})** |
| inflation pass-through | b | **{f.b:.4f}** |
| annual rate shock | sigma | **{f.sigma:.5f}  ({f.sigma:.2%})** |

These are the values `rate_model.py` bakes in as `DEFAULT_ADJUST_SPEED`,
`DEFAULT_REAL_INTERCEPT`, `DEFAULT_INFLATION_BETA`, and `DEFAULT_RATE_SIGMA`
(computed at import from the same data, so the simulator and this report cannot
drift apart). The simulated rate path starts from a current-level initial rate,
`DEFAULT_INITIAL_RATE = {rate_model.DEFAULT_INITIAL_RATE:.1%}` (the {y1} GS10
annual average), and is floored at {rate_model.RATE_FLOOR:.0%}.

## 5. Interpretation

- **Long-run pass-through `b` = {f.b:.2f}** -- slightly above one-for-one,
  consistent with the long-run Fisher relationship (and the tax-augmented Darby
  variant, which predicts a coefficient above unity) [3].
- **Adjustment speed `lam` = {f.lam:.2f}** -- only about {f.lam:.0%} of the gap to
  the Fisher target closes each year, so the rate is **sluggish**. When inflation
  jumps, the nominal rate lags and the *implied real rate* (`i - pi`) compresses
  and can turn negative -- the Mundell-Tobin / short-run "Fisher puzzle" behaviour
  actually seen in 2021-2022 [4]. The long-run real rate settles near
  a + (b-1)&middot;pi: about **{long_run_real:.2%}** at 2.5% inflation.
- **Steady state.** At a constant 2.5% inflation the rate converges to
  a + b&middot;0.025 = **{steady:.2%}**, close to the ~5% level at which the local
  annuity pricer matches market quotes, and to the recent 10-year yield.
- **Shock size `sigma` = {f.sigma:.2%}** -- the typical one-year surprise in the
  rate beyond what persistence and inflation explain.

## 6. Scope and caveats

- Per the *layered* design, only the **interest** equation is fit here. Inflation
  itself is not parametrically modelled: in simulation it comes from the block
  bootstrap of historical equity/inflation pairs (`equity_model.py`), so there is
  no separate inflation AR to estimate.
- The rate innovation `eps_t` is drawn independently of the equity/inflation
  innovations (a simplification; their historical residual correlation is small).
- The fit uses the GS10 sample ({y0}-{y1}); a different yield maturity, frequency
  (year-end vs. average), or window would shift the estimates. The series and
  retrieval are pinned in `market_data.py`.

## References

1. Federal Reserve Bank of St. Louis, FRED, *Market Yield on U.S. Treasury
   Securities at 10-Year Constant Maturity (GS10).*
   https://fred.stlouisfed.org/series/GS10
2. U.S. Bureau of Labor Statistics, *CPI-U*, via *Historical Inflation Rates.*
   https://www.usinflationcalculator.com/inflation/historical-inflation-rates/
3. Fisher, I. (1930). *The Theory of Interest.* Macmillan. (Darby, M. R. (1975),
   *The Financial and Tax Effects of Monetary Policy on Interest Rates*, for the
   above-unity tax-augmented coefficient.)
4. Mundell, R. (1963). *Inflation and Real Interest.* Journal of Political
   Economy, 71(3); Tobin, J. (1965). *Money and Economic Growth.* Econometrica,
   33(4).
"""


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Fit and document the dynamic "
                                "annuity-rate model.")
    p.add_argument("--markdown", action="store_true",
                   help="(re)write FIT.md, the fit-documentation source")
    args = p.parse_args(argv)

    fit = rate_model.fit_interest_model()
    if args.markdown:
        path = os.path.join(_HERE, "FIT.md")
        with open(path, "w") as fh:
            fh.write(markdown_report(fit))
        print(f"wrote {path}")
    else:
        print(text_report(fit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
