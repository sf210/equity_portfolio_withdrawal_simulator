# Equity Portfolio Withdrawal Simulator — Methodology

*How the Monte Carlo simulation works, and the data and research it rests on.*

[TOC]

## 1. What is being modeled

The simulator evaluates a retirement spending strategy that **keeps the money
invested in equities** and, each year, withdraws **what a life annuity *would*
pay** on the current balance. It is explicitly **not** a model of buying an
annuity: there is no mortality pooling and no income guarantee, so a poor
sequence of early returns can deplete the balance. The annuity payout is used
only as a *spending rule* — a longevity-aware way to decide how much to take each
year.

A single run projects one random path; the Monte Carlo driver repeats this over
thousands of paths and reports the distribution of outcomes.

The pieces and their data flow:

```
Pricing (per-year annuity payout):
    SOA 2012 IAM tables ──> annuity_pricing.py   (local, default)
    immediateannuities.com ──> annuity_quote.py  (optional: --quotes site)

Scenarios:
    market_data.py ──> equity_model.py  (equity + inflation, 1928–2025)

Simulation:
    withdrawal_projection.py  (one path)  ──>  montecarlo.py  (many paths + CIs)
```

## 2. The equity and inflation scenario model

Each projected year needs a **nominal equity return** (to grow the account) and
an **inflation rate** (to express results in today's dollars). Because equity
returns and inflation are correlated, they are drawn **jointly** rather than
independently. The models are calibrated to paired annual data for **1928–2025**
(98 years):

- **S&P 500 nominal total return** (dividends reinvested), from Damodaran / NYU
  Stern [4].
- **CPI-U annual-average inflation** (U.S. Bureau of Labor Statistics, via
  usinflationcalculator.com) [5].

Three scenario generators are available (`equity_model.py`):

- **Bootstrap** (default) — resample actual historical year-pairs with
  replacement (IID). Preserves the empirical distribution: fat left tail, skew,
  and the contemporaneous equity/inflation correlation. Historical resampling is
  preferred over normal-based Monte Carlo for retirement risk work, because the
  normal assumption understates tail risk and overstates safe withdrawal rates
  [1, 2].
- **Block** — circular block bootstrap [3]: resample consecutive runs of
  `block_length` years (default 5) and stitch them together, wrapping around the
  end of the series. Unlike the IID bootstrap this preserves **serial
  correlation** — momentum, mean reversion, and the multi-year persistence of
  inflation — which widens the left tail of multi-year outcomes.
- **Lognormal** — fit a bivariate normal to `(log(1+equity), log(1+inflation))`
  and draw from it. Smooth and able to extrapolate, but has zero skew/kurtosis
  and so understates tail risk; the fitted covariance still reproduces the
  historical correlation.

### 2.1 Two inflation modes

The simulator supports two ways of handling inflation:

- **Constant** (default). Inflation is a single assumption (`--inflation`, default
  **2.5%**), used only to deflate results to today's dollars, and the annuity
  discount rate is fixed (`--interest`, default 3.5%). To keep the equity series
  consistent with the constant assumption, each sampled year's *nominal* equity
  return is **restated** onto that basis — its embedded historical inflation is
  stripped out (preserving the real return) and the constant rate re-applied:

  ```
  real     = (1 + nominal) / (1 + historical_inflation) − 1
  restated = (1 + real) × (1 + assumed_inflation) − 1
  ```

  so the historical inflation once correlated with equity has no residual effect.

- **Dynamic** (`--dynamic-rates`). Inflation is *not* held constant: each path
  uses its own per-year sampled inflation directly (from the block bootstrap, so
  persistence is preserved), it deflates results to today's dollars, **and** it
  drives an evolving annuity discount rate. Equity is used as drawn (no
  restatement), so the historical equity/inflation pairing stays intact.
  Section 7 specifies and estimates this mode.

## 3. Annuity pricing (local SOA-table model)

By default the per-year payout is priced **offline** from published mortality
tables (`annuity_pricing.py`); live quotes from immediateannuities.com [6] are an
opt-in alternative (`--quotes site`).

### 3.1 Mortality tables

The base mortality is the **Society of Actuaries 2012 Individual Annuity
Mortality (IAM) Basic Table**, by sex, age-nearest-birthday [7]:

- `soa_mortality_2581.csv` — *2012 IAM Basic Table – Male, ANB* (ages 0–120)
- `soa_mortality_2582.csv` — *2012 IAM Basic Table – Female, ANB* (ages 0–120)

These are **annuitant** tables: annuitants are healthier and longer-lived than
the general population. Optional generational mortality improvement uses **SOA
Projection Scale G2** [7]:

- `soa_mortality_2583.csv` — *Projection Scale G2 – Male, ANB* (ages 0–105)
- `soa_mortality_2584.csv` — *Projection Scale G2 – Female, ANB* (ages 0–105)

### 3.2 Actuarial present value

With a flat interest rate `i` and survival probabilities `tpx` (the probability a
life now aged `x` survives `t` years, built from the table's one-year mortality
rates `q_x`), the actuarial present value of \$1 per year of income paid
**monthly, in arrears, while alive** is [8]:

```
v        = 1 / (1 + i)
a_x      = sum over t ≥ 1 of v^t · tpx        (annual annuity-immediate)
a_x^(12) ≈ a_x + 11/24                         (Woolhouse 2-term, m = 12)
```

The premium buys income at that price, so the **level annual payout** is

```
annual_payout = premium / a_x^(12).
```

For two lives, a **last-survivor** annuity pays while *either* is alive; its
factor follows from inclusion–exclusion [8],

```
a_LS = a_x + a_y − a_xy,
```

where `a_xy` (both alive) uses the product of the two independent survival
curves, with the same +11/24 monthly adjustment. The table's top age (120) is
treated as certain death, so the survival curve terminates cleanly.

### 3.3 Mortality improvement (Scale G2)

With `--improvement`, the 2012 base rates are projected forward **generationally**
to the quote year [7]:

```
q_a(year) = q_a(2012) · (1 − g2_a)^(year − 2012),
```

applied as each cohort ages, so the calendar year at attained age `a` is
`quote_year + (a − start_age)`. Improvement lengthens lifespans and therefore
*lowers* the payout. (Scale G2 grades to zero by its terminal age; attained ages
beyond it receive no further improvement.)

### 3.4 Calibration against the market

The model carries **no insurer expense, profit, or interest-rate load**, so it is
a clean actuarial benchmark rather than a marketed quote. Compared against live
immediateannuities.com quotes [6] for ages 60/65/70/80, the model pays roughly
**80–94%** of the site at the default 3.5% interest, and **matches the site at
about 5%** interest. That ~5% is consistent with a current 10-year nominal yield
of roughly a 2.3% real rate plus ~2.5% inflation (Section 7).

## 4. The withdrawal mechanism (one path)

Starting from the invested `amount`, for each projected year
(`withdrawal_projection.py`):

1. Price the monthly annuity payout per dollar at the current age and balance
   (Section 3); the payout is linear in premium, so one rate per age is computed
   and scaled.
2. Withdraw **12 ×** that monthly payout from the balance.
3. Grow the remaining balance by that year's nominal equity return.
4. Increment the age(s) by one and repeat.

Optional `--upper-bound` / `--lower-bound` cap and floor the annual withdrawal
**in today's dollars**, as factors of year 1's withdrawal (e.g. cap at 1.2× and
floor at 0.5×); the clamp is applied to the cash actually withdrawn, so it feeds
back into the surviving balance.

## 5. Monte Carlo aggregation

`montecarlo.py` runs many independent paths (default **5,000**) and summarizes
the distribution:

- **Ending balance**, in both nominal and today's dollars: mean, median, and the
  central **80% / 90% / 95% / 99%** confidence intervals. A "C% interval" is the
  central range covering C% of outcomes — the `[(100−C)/2, 100−(100−C)/2]`
  percentile band (e.g. 80% = 10th–90th percentile).
- **Annual payout by year**, in today's dollars: the same statistics, per year.
- **Downside**: the share of paths whose real ending balance finishes below the
  starting amount, and below half of it.
- **Worst real returns**: the worst single-year and worst cumulative five-year
  *real* (inflation-adjusted) equity total return seen anywhere in the run.

The annuity-rate cache is built once per run and reused across all paths, so
pricing cost (and any network traffic) stays at roughly one rate per age
regardless of the number of simulations.

## 6. Key assumptions and caveats

- This models withdrawing the annuity-*equivalent* amount while staying invested.
  It is **not** an annuity purchase — no mortality pooling, no income guarantee.
  Because the full annuity payout includes return of principal, the withdrawal
  rate is high and the real balance typically erodes; single-life runs commonly
  finish below the starting amount in real terms. This is expected model
  behavior, not a defect.
- Local pricing omits insurer loads, so it is an actuarial benchmark, not a
  quotable rate; results are sensitive to the assumed interest rate.
- Historical calibration assumes the 1928–2025 distribution is informative about
  the future, which may not hold.
- Mortality follows population-level annuitant tables; no individual health
  underwriting is performed.

## 7. Dynamic inflation and interest rates

The dynamic mode (`--dynamic-rates`, `rate_model.py`) makes inflation vary year
to year and ties the annuity discount rate to it, so a higher-inflation path
produces higher nominal yields and a larger nominal annuity payout. Because
inflation and bond yields are persistent, correlated time series, the discount
rate is modelled with **lagged** dependence rather than as a static function of
the current year's inflation.

### 7.1 Specification

The design is **layered**: inflation keeps coming from the block bootstrap of
Section 2 (which already preserves its serial persistence and its pairing with
equity), and only the interest rate is added as a parametric process. The rate
partially adjusts each year toward a long-run **Fisher target** driven by the
*previous* year's inflation:

```
i*_t = a + b · π_{t−1}                                  (long-run Fisher target)
i_t  = (1 − λ) · i_{t−1} + λ · i*_t + ε_t,   ε_t ~ N(0, σ²)
```

`a` is the real-rate intercept, `b` the long-run inflation pass-through, and `λ`
the annual speed of adjustment. The rate in year *t* therefore depends on **both**
the prior year's rate (weight `1 − λ`) and the prior year's inflation. Year 1 is
priced at a given initial ("today's") rate `i₀` (`--initial-rate`, default 4.3% ≈
the current 10-year yield); the rate is floored at zero. The interest innovation
is drawn independently of the equity/inflation draws — a deliberate
simplification (see §7.5).

### 7.2 Estimation

The model is fit as the reduced form

```
i_t = c + ρ · i_{t−1} + δ · π_{t−1} + ε_t
```

by ordinary least squares, then mapped to the structural parameters via
`λ = 1 − ρ`, `a = c / λ`, `b = δ / λ`. The data are annual averages of the
**10-year Treasury constant-maturity yield** (Federal Reserve / FRED series
`GS10`, which begins in 1953) [11] and **CPI-U inflation** [5]; the usable sample
is **1954–2025 (n = 72)**. `rate_model.fit_interest_model()` reproduces this fit
(the script `fit_rate_model.py` prints it and regenerates the focused fit report
`FIT.md`/`FIT.pdf`), and the package defaults are exactly these estimates.

**Exhibit 1 — OLS estimates** (dependent variable: 10-year yield `i_t`):

| Term | Coefficient | Std. error | t-stat |
|------|------------:|-----------:|-------:|
| constant `c` | 0.00279 | 0.00202 | 1.38 |
| `i_{t−1}` (ρ) | 0.83477 | 0.04238 | 19.70 |
| `π_{t−1}` (δ) | 0.18645 | 0.04478 | 4.16 |

n = 72 (1954–2025)  ·  R² = 0.927  ·  adj. R² = 0.925  ·  residual σ = 0.79 pp  ·
Durbin–Watson = 1.95.

Mapped to structural parameters:

```
λ = 1 − ρ = 0.165      (annual adjustment speed)
a = c / λ = 1.69%      (real-rate intercept)
b = δ / λ = 1.13       (long-run inflation pass-through)
σ = 0.79 pp            (innovation standard deviation)
```

The lagged yield is overwhelmingly significant (t ≈ 20) and the lagged-inflation
term is significant (t ≈ 4.2); the model explains 93% of the variation in the
yield, and the Durbin–Watson near 2 indicates essentially no residual
autocorrelation — the lagged specification has absorbed the dynamics.

![Exhibit 1: actual vs. fitted 10-year yield](doc_yield_fit.png)

![Exhibit 2: regression residuals over time](doc_yield_residuals.png)

![Exhibit 3: residual distribution](doc_resid_hist.png)

### 7.3 Implied dynamics

The estimates have a clear economic reading:

- **Long-run pass-through `b ≈ 1.13`** is slightly above one, consistent with the
  tax-augmented (Darby) form of the Fisher hypothesis.
- **Adjustment speed `λ ≈ 0.165`** is *small*: only about one-sixth of the gap to
  the Fisher target closes each year. This is the sluggish short-run pass-through
  (the Mundell–Tobin / "Fisher puzzle" effect, §7.4).
- The **long-run real rate is ≈ `a` = 1.7%**, and the steady-state nominal rate at
  2.5% inflation is `a + b·2.5% ≈ 4.5%` — close to both the current 10-year yield
  and the ~5% that reproduces live annuity quotes (§3.4).

Crucially, because `λ` is small, when inflation jumps the rate lags and the
**implied real rate `i_t − π_t` compresses and can go temporarily negative**,
recovering only as the rate catches up — exactly the 2021–2022 experience —
while the long-run real rate stays near 1.7%. Exhibit 4 illustrates this with a
deterministic inflation spike.

![Exhibit 4: rate lags an inflation spike; the real rate dips negative](doc_rate_illustration.png)

### 7.4 Research basis

The specification follows established findings on the yield/inflation link:

- **Fisher relationship [9].** A nominal yield ≈ expected real rate + expected
  inflation + term premium; over long horizons the pass-through is roughly
  one-for-one (cointegration evidence across OECD countries) — consistent with the
  fitted `b ≈ 1.1`.
- **Sluggish short-run pass-through (Mundell–Tobin / "Fisher puzzle") [10].** In
  the short run the pass-through is well below one, so when inflation jumps,
  nominal yields lag and the real rate compresses — captured here by the small
  fitted `λ` and the lagged inflation term.
- **The real rate is not constant — and not always positive [11, 12, 13].** The
  10-year TIPS (market real) yield was negative from December 2011 through ~2013
  and deeply negative in 2020–2022 (a record-low −0.93% 10-year TIPS auction in
  July 2020, around −1.2% in 2021). On a realized basis the divergence was
  extreme: with CPI near 7% at end-2021 and a 9.1% peak in mid-2022 against a
  10-year yield of ~1.5–3%, the **ex-post real yield was roughly −5% to −6%**. It
  is about +2.3% as of mid-2026. The error-correction model reproduces this
  behavior endogenously while remaining mean-reverting, so it cannot drift to
  implausible levels over a long horizon.

### 7.5 Usage and caveats

Enable with `--dynamic-rates` (local pricing only); set the starting rate with
`--initial-rate`. Caveats specific to this mode:

- The interest innovation `ε_t` is drawn **independently** of the equity and
  inflation draws. Contemporaneous correlation between rate shocks and
  equity/inflation is therefore omitted; this is a simplification, not an
  estimate of zero correlation.
- Parameters are fit on **1953–2025** (the span of the GS10 series), a shorter
  window than the 1928–2025 equity/inflation data, and assume that historical
  yield/inflation relationship continues to hold.
- The model is of the **nominal** rate; the "larger payout" from higher inflation
  is largely a nominal effect, and is deflated away when results are expressed in
  today's dollars (a level annuity loses real value faster under high inflation).

## References

1. Pfau, W. D. (2010). *An International Perspective on Safe Withdrawal Rates: The
   Demise of the 4 Percent Rule?* Journal of Financial Planning, 23(12).
2. Efron, B. (1979). *Bootstrap Methods: Another Look at the Jackknife.* The
   Annals of Statistics, 7(1), 1–26.
3. Politis, D. N., & Romano, J. P. (1992). *A Circular Block-Resampling Procedure
   for Stationary Data.* In *Exploring the Limits of Bootstrap*, Wiley. (See also
   Künsch, H. R. (1989), Annals of Statistics 17(3), 1217–1241.)
4. Damodaran, A. *Historical Returns on Stocks, Bonds and Bills: 1928–Current.*
   NYU Stern. https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histretSP.html
5. U.S. Bureau of Labor Statistics, *CPI-U*, via *Historical Inflation Rates.*
   https://www.usinflationcalculator.com/inflation/historical-inflation-rates/
6. ImmediateAnnuities.com. *Average estimated immediate-annuity income quotes.*
   https://www.immediateannuities.com/
7. Society of Actuaries / American Academy of Actuaries, Life Experience
   Subcommittee (2011). *2012 Individual Annuity Reserving (IAR) Table and 2012
   IAM Basic Table, with Projection Scale G2.* SOA Mortality and Other Rate Tables
   (mort.soa.org), table identities 2581–2584.
   https://mort.soa.org/ViewTable.aspx?TableIdentity=2584
8. Dickson, D. C. M., Hardy, M. R., & Waters, H. R. (2020). *Actuarial
   Mathematics for Life Contingent Risks* (3rd ed.). Cambridge University Press —
   life annuities, the Woolhouse `m`-thly formula, and multiple-life (last
   survivor) functions.
9. Fisher, I. (1930). *The Theory of Interest.* Macmillan.
10. Mundell, R. (1963). *Inflation and Real Interest.* Journal of Political
    Economy, 71(3); Tobin, J. (1965). *Money and Economic Growth.* Econometrica,
    33(4). (Mundell–Tobin effect / short-run Fisher "puzzle.")
11. Federal Reserve Bank of St. Louis, FRED. *Market Yield on U.S. Treasury
    Securities at 10-Year Constant Maturity* — series **GS10** (monthly, averaged
    to annual; used to fit the interest-rate model in `rate_model.py`), with
    **DGS10** (daily nominal) and **DFII10** (inflation-indexed/real).
    https://fred.stlouisfed.org/series/GS10
12. American Enterprise Institute. *Treasury Yields, Inflation, and Real Interest
    Rates: Analyzing the Historical Record.*
    https://www.aei.org/economics/treasury-yields-inflation-and-real-interest-rates-analyzing-the-historical-record/
13. *New 10-Year TIPS Gets Real Yield of −0.93%, Lowest in History.* Seeking
    Alpha (July 2020).
