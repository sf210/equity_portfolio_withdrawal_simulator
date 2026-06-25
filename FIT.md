# Dynamic Annuity-Rate Model -- Fit Report

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
| Sample | **1954-2025** (n = **72** annual observations) |
| Estimation | Ordinary least squares (reduced form), `numpy.linalg.lstsq` |

GS10 begins in 1953; the lagged regressors drop the first year, so estimation
starts in 1954. The yield series lives in `market_data.py`
(`treasury_10y_regression_data()`); the regression is `rate_model.fit_interest_model()`.

## 3. Reduced-form regression

`i_t = c + rho * i_(t-1) + delta * pi_(t-1) + eps_t`

| term | coef | std err | t |
|---|---:|---:|---:|
| c (intercept) | 0.00279 | 0.00202 | 1.38 |
| rho &middot; i_(t-1) | 0.83457 | 0.04242 | 19.67 |
| delta &middot; pi_(t-1) | 0.18661 | 0.04482 | 4.16 |

R&sup2; = **0.9267**, adjusted R&sup2; = 0.9246, residual sigma =
**0.00786 (0.79%)**, Durbin-Watson = **1.945**.

The high `rho` (0.835, t = 19.7) confirms the strong
persistence of yields; the significant `delta` (0.187, t =
4.2) is the inflation pass-through. The Durbin-Watson near 2 means
the residuals show little remaining first-order autocorrelation, so the AR(1)-in-
levels specification is adequate. The intercept `c` is not individually
significant (t = 1.38), which is expected -- the long-run real rate is
weakly identified separately from the persistence term.

## 4. Structural parameters

Mapping `lam = 1 - rho`, `a = c / lam`, `b = delta / lam`, with `sigma` the
residual standard deviation:

| parameter | symbol | value |
|---|---|---:|
| adjustment speed | lam | **0.1654** |
| real-rate intercept | a | **0.01688  (1.69%)** |
| inflation pass-through | b | **1.1280** |
| annual rate shock | sigma | **0.00786  (0.79%)** |

These are the values `rate_model.py` bakes in as `DEFAULT_ADJUST_SPEED`,
`DEFAULT_REAL_INTERCEPT`, `DEFAULT_INFLATION_BETA`, and `DEFAULT_RATE_SIGMA`
(computed at import from the same data, so the simulator and this report cannot
drift apart). The simulated rate path starts from a current-level initial rate,
`DEFAULT_INITIAL_RATE = 4.3%` (the 2025 GS10
annual average), and is floored at 0%.

## 5. Interpretation

- **Long-run pass-through `b` = 1.13** -- slightly above one-for-one,
  consistent with the long-run Fisher relationship (and the tax-augmented Darby
  variant, which predicts a coefficient above unity) [3].
- **Adjustment speed `lam` = 0.17** -- only about 17% of the gap to
  the Fisher target closes each year, so the rate is **sluggish**. When inflation
  jumps, the nominal rate lags and the *implied real rate* (`i - pi`) compresses
  and can turn negative -- the Mundell-Tobin / short-run "Fisher puzzle" behaviour
  actually seen in 2021-2022 [4]. The long-run real rate settles near
  a + (b-1)&middot;pi: about **2.01%** at 2.5% inflation.
- **Steady state.** At a constant 2.5% inflation the rate converges to
  a + b&middot;0.025 = **4.51%**, close to the ~5% level at which the local
  annuity pricer matches market quotes, and to the recent 10-year yield.
- **Shock size `sigma` = 0.79%** -- the typical one-year surprise in the
  rate beyond what persistence and inflation explain.

## 6. Scope and caveats

- Per the *layered* design, only the **interest** equation is fit here. Inflation
  itself is not parametrically modelled: in simulation it comes from the block
  bootstrap of historical equity/inflation pairs (`equity_model.py`), so there is
  no separate inflation AR to estimate.
- The rate innovation `eps_t` is drawn independently of the equity/inflation
  innovations (a simplification; their historical residual correlation is small).
- The fit uses the GS10 sample (1954-2025); a different yield maturity, frequency
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
