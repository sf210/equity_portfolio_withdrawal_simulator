# Equity Portfolio Withdrawal Simulator

Tools for projecting retirement withdrawals under a strategy that keeps the money
invested in equities and each year withdraws what a **life annuity would pay** on
the current balance — then stress-tests that strategy with Monte Carlo simulation.

Live annuity quotes come from [immediateannuities.com](https://www.immediateannuities.com/);
equity-return and inflation scenarios are driven by historical S&P 500 and CPI
data (1928–2025).

## Disclaimer

**These programs are for educational purposes only and must not be taken as
financial advice.** How to allocate investments varies between individuals and is
**not** contemplated in any of the analysis performed by the programs in this
repository. The projected cashflows from the investment strategies modeled here
are **speculative** and are likely to differ **significantly** from actual
experience going forward.

The scripts in this repository likely contain errors. There is **ABSOLUTELY NO
WARRANTY** for the software in this repository; see the [License](#license) for
the full warranty disclaimer and limitation of liability.

Additional modeling caveats: this models withdrawing the annuity-*equivalent*
amount while staying invested — it is **not** an annuity purchase, so there is no
mortality pooling and no income guarantee. Because the annuity payout includes
return of principal, the withdrawal rate is high and the real balance typically
erodes over time. Annuity quotes are "average estimated" figures, not binding
offers.

## Setup

Requires **Python 3.14** and network access (for live annuity quotes). The only
third-party dependency is NumPy.

```bash
git clone git@github.com:sf210/equity_portfolio_withdrawal_simulator.git
cd equity_portfolio_withdrawal_simulator

python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

The virtual environment is intentionally **not** committed (it is large and
platform-specific); recreate it from `requirements.txt` as above. `.venv/` is
gitignored.

## How it fits together

Data flows one direction, from a live quote + historical data into a projection:

```
immediateannuities.com ──> annuity_quote.py ─┐
                                             ├─> withdrawal_projection.py ──> montecarlo.py
market_data.py ──> equity_model.py ──────────┘     (one random path)         (many paths + CIs)
```

## The scripts

### `annuity_quote.py`
Looks up the monthly life-annuity payout for a lump sum. It submits the
immediateannuities.com quote form (assuming income begins in 1 month) and reads
the dollar figure in the "Life" row. Uses only the standard library.

- **Inputs:** `amount age gender state`, plus optional `--joint-age` /
  `--joint-gender` for a joint-life (two-person) annuity.
- **Output:** the monthly payout as a bare number (no `$` or commas), so it pipes
  cleanly. Importable as `get_life_quote(...)`, which returns a `"$NNN"` string.

```bash
python annuity_quote.py 100000 65 M FL
# -> 685

python annuity_quote.py 250000 70 female CA --joint-age 68 --joint-gender M

# pipeable:
python annuity_quote.py 100000 65 M FL | awk '{print $1*12}'
```

### `market_data.py`
Not a CLI — a data module. Holds the paired historical series of S&P 500 nominal
total returns and CPI annual-average inflation, 1928–2025, keyed by year so the
two stay aligned. Exposes `equity_returns()` and `inflation_rates()` as decimal
fractions.

### `equity_model.py`
The scenario generator. `JointReturnModel` samples one-year `(equity return,
inflation)` pairs **jointly**, preserving the historical equity/inflation
relationship. Three modes:

- **`bootstrap`** (default) — resample actual historical year-pairs (IID).
  Preserves the real distribution's fat left tail and skew.
- **`block`** — circular block bootstrap: resample consecutive runs of
  `block_length` years (default 5) to also preserve *serial* correlation
  (notably inflation's strong year-to-year persistence).
- **`lognormal`** — draw from a bivariate normal fitted to the log series; smooth
  but understates tail risk.

Run it directly to print the calibrated statistics:

```bash
python -c "from equity_model import JointReturnModel; print(JointReturnModel('block').summary())"
```

### `withdrawal_projection.py`
Simulates **one** random 30-year path. Each year it: looks up the annuity payout
for the current balance and age (the payout is linear in premium, so a single
$100k quote per age is fetched and scaled), withdraws 12× that monthly payout,
grows the remainder by that year's equity return, then ages everyone by one year.
Quote ages above 90 are clamped to the age-90 rate (the quote site's maximum).

- **Inputs:** `amount age gender state` plus `--joint-age`/`--joint-gender`,
  `--years` (default 30), `--model`, `--block-length`, `--seed`.
- **Output:** a calibration header, a year-by-year table (balance, **annual**
  payout in nominal and today's dollars, that year's equity return and
  inflation), and the ending balance in nominal and today's dollars.

```bash
# reproducible single path
python withdrawal_projection.py 1000000 65 M FL --seed 1

# joint life, lognormal model
python withdrawal_projection.py 1000000 65 M FL \
    --joint-age 63 --joint-gender F --model lognormal

# block bootstrap with 10-year blocks
python withdrawal_projection.py 1000000 70 F CA --model block --block-length 10
```

Reusable functions for callers: `build_rate_cache(...)` and `simulate_path(...)`.

### `montecarlo.py`
Runs **many** paths (default 500) and reports the distribution of outcomes: the
mean, median, and 80% / 90% / 95% / 99% confidence intervals for both the ending
balance (nominal and today's dollars) and the **annual** payout by year. It builds
the annuity-rate cache once and reuses it across every path, so total network
traffic stays at ~one quote per age regardless of the number of simulations.

- **Inputs:** same as `withdrawal_projection.py`, plus `--sims` (default 500) and
  `--nominal` (show the payout table in nominal instead of today's dollars).
- A "C% confidence interval" is the central interval covering C% of outcomes
  (e.g. 80% = the 10th–90th percentile range).

```bash
# default 500-path run
python montecarlo.py 1000000 65 M FL

# 2000 paths, block bootstrap, fixed seed
python montecarlo.py 1000000 65 M FL --sims 2000 --model block --seed 1

# joint life, payout table in nominal dollars
python montecarlo.py 1000000 65 M FL --joint-age 63 --joint-gender F --nominal
```

## Man pages

Two troff man pages are included (section 1):

- `withdrawal_projection.1`
- `montecarlo.1`

View them without installing:

```bash
man ./withdrawal_projection.1
man ./montecarlo.1
```

(`annuity_quote.py`, `equity_model.py`, and `market_data.py` do not have man
pages; see the docstrings and `--help`.)

## License

Licensed under the [Mozilla Public License 2.0](LICENSE). The software is provided
"as is", without warranty of any kind — see Sections 6 ("Disclaimer of Warranty")
and 7 ("Limitation of Liability") of the license.
