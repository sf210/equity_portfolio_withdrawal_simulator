#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Project annuity-equivalent withdrawals from an equity-invested account.

Strategy modelled (this is NOT buying an annuity -- it keeps the money invested
in equities and withdraws what a life annuity *would* pay):

  Starting balance = amount invested. For each of N years:
    1. Price the monthly life-annuity payout for the CURRENT balance at the
       CURRENT age. By default this is the local SOA-table pricer
       (annuity_pricing, offline); --quotes site instead fetches live
       immediateannuities.com quotes. The payout is linear in premium, so one
       rate per age is computed/quoted and scaled to the balance.
    2. Withdraw 12 x that monthly payout from the balance.
    3. Grow the remaining balance by that year's nominal equity return.
    4. Age (and any joint age) increases by 1; repeat.

Equity returns are drawn from the equity_model as historical nominal returns,
then restated onto the constant-inflation assumption (--inflation, default
2.5%): each sampled year's embedded historical inflation is stripped out --
preserving its real return -- and the constant rate is applied instead (see
restate_equity_at_inflation). So inflation has one constant effect, on both the
equity nominal return and the deflation of results to today's dollars; the
historical inflation that was correlated with equity is ignored. Results are
reported in nominal dollars (the Monte Carlo follow-up reports in today's
dollars).

Optional --upper-bound / --lower-bound put a cap and floor on the annual
withdrawal, expressed in today's dollars as a factor of year 1's withdrawal:
e.g. with a $50,000 year-1 withdrawal, --upper-bound 1.2 caps any later year at
$60,000 (today's $) and --lower-bound 0.5 floors it at $25,000 (today's $).

The local pricer handles any age; with --quotes site the site only quotes ages
40-90, so quote ages above 90 are clamped to 90 (conservative: it understates
the rising payout rate at very old ages).

This module exposes build_rate_cache() and simulate_path() for reuse by the
Monte Carlo (many-paths / confidence-interval) follow-up.

Example:
    python withdrawal_projection.py 1000000 65 M FL
    python withdrawal_projection.py 1000000 65 M FL --interest 0.04 --improvement
    python withdrawal_projection.py 1000000 65 M FL --quotes site \
        --joint-age 63 --joint-gender F --model lognormal --seed 1
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error

import numpy as np

import annuity_pricing
import annuity_quote
import rate_model
from equity_model import JointReturnModel

REF_PREMIUM = 100_000  # payout is linear in premium; quote this and scale.
SITE_MAX_AGE = 90      # immediateannuities.com dropdown maximum.
DEFAULT_INFLATION = 0.025  # constant annual CPI assumption (2.5%).
DEFAULT_QUOTES = "local"   # pricing source: local SOA-table model vs. the site.


class AnnuityRateCache:
    """Caches the monthly life-annuity payout *per dollar of premium*, by age.

    Because the payout scales linearly with premium, one $100k quote per
    (age, joint_age) is enough; the rate is reused across years and across many
    Monte Carlo paths. Quote ages above the site maximum are clamped.
    """

    def __init__(self, gender: str, state: str, joint_gender: str | None = None):
        self.gender = gender
        self.state = state
        self.joint_gender = joint_gender
        self._cache: dict[tuple[int, int | None], float] = {}

    def monthly_rate(self, age: int, joint_age: int | None = None) -> float:
        q_age = min(age, SITE_MAX_AGE)
        q_joint = min(joint_age, SITE_MAX_AGE) if joint_age is not None else None
        key = (q_age, q_joint)
        if key not in self._cache:
            payment = annuity_quote.get_life_quote(
                amount=REF_PREMIUM,
                age=q_age,
                gender=self.gender,
                state=self.state,
                joint_age=q_joint,
                joint_gender=self.joint_gender,
            )
            monthly = int(re.sub(r"[$,]", "", payment))
            self._cache[key] = monthly / REF_PREMIUM
        return self._cache[key]


class LocalRateCache:
    """Monthly payout *per dollar of premium*, by age, from annuity_pricing.

    A drop-in replacement for AnnuityRateCache that prices each rate locally from
    the SOA mortality tables (no network) at a fixed interest rate, optionally
    with Scale G2 mortality improvement. The local pricer handles any age, so --
    unlike the site cache -- ages above 90 are NOT clamped.
    """

    def __init__(self, gender: str, joint_gender: str | None = None,
                 interest_rate: float = annuity_pricing.DEFAULT_INTEREST,
                 improvement: bool = False, quote_year: int | None = None):
        self.gender = gender
        self.joint_gender = joint_gender
        self.interest_rate = interest_rate
        self.improvement = improvement
        self.quote_year = quote_year
        self._cache: dict[tuple[int, int | None], float] = {}

    def monthly_rate(self, age: int, joint_age: int | None = None,
                     interest: float | None = None) -> float:
        # interest=None uses the cache's fixed rate; otherwise price at the given
        # rate (bucketed to 1bp so dynamic-rate paths still reuse the cache).
        if interest is None:
            rate = self.interest_rate
            key = (age, joint_age, None)
        else:
            rate = round(interest, 4)
            key = (age, joint_age, rate)
        if key not in self._cache:
            if joint_age is None:
                annual = annuity_pricing.single_life_annuity(
                    1.0, age, self.gender, rate,
                    self.improvement, self.quote_year)
            else:
                annual = annuity_pricing.last_survivor_annuity(
                    1.0, age, self.gender, joint_age, self.joint_gender,
                    rate, self.improvement, self.quote_year)
            self._cache[key] = annual / 12.0
        return self._cache[key]


def build_rate_cache(gender: str, state: str, joint_gender: str | None = None,
                     prefetch_from_age: int | None = None, years: int = 30, *,
                     source: str = DEFAULT_QUOTES,
                     interest_rate: float = annuity_pricing.DEFAULT_INTEREST,
                     improvement: bool = False, quote_year: int | None = None):
    """Create a rate cache, optionally pre-warming every age it will need.

    source="local" (default) prices from the SOA tables via annuity_pricing
    (offline; honours interest_rate / improvement / quote_year and ignores
    state). source="site" fetches live immediateannuities.com quotes (the
    original behaviour; ignores interest_rate / improvement). Pre-fetching warms
    the cache with one entry per distinct age up front -- essential for the site
    source (one network call each) and harmless for the local one."""
    if source == "site":
        cache = AnnuityRateCache(gender, state, joint_gender)
    elif source == "local":
        cache = LocalRateCache(gender, joint_gender, interest_rate,
                               improvement, quote_year)
    else:
        raise ValueError(f"unknown quotes source {source!r}; use 'local' or 'site'")
    if prefetch_from_age is not None:
        has_joint = joint_gender is not None
        for offset in range(years):
            cache.monthly_rate(
                prefetch_from_age + offset,
                (prefetch_from_age + offset) if has_joint else None,
            )
    return cache


def restate_equity_at_inflation(equity_returns, hist_inflation, inflation):
    """Restate historical nominal equity returns onto the constant-inflation basis.

    Each sampled equity return is a *nominal* historical figure that embeds the
    actual inflation of its source year. To make the simulation use a single
    constant inflation rate, we strip that embedded inflation out -- preserving
    the year's *real* equity return -- and re-apply the constant `inflation`:

        real    = (1 + nominal) / (1 + hist_inflation) - 1
        restated = (1 + real) * (1 + inflation) - 1

    All arguments are decimal fractions; equity_returns / hist_inflation are
    arrays of equal length, `inflation` is a scalar. Returns the restated
    nominal equity returns. After this, deflating by the constant inflation
    recovers exactly the historical real return, so inflation has no residual
    effect on equity beyond the single constant assumption.
    """
    real = (1.0 + np.asarray(equity_returns, dtype=float)) / (1.0 + np.asarray(
        hist_inflation, dtype=float)) - 1.0
    return (1.0 + real) * (1.0 + inflation) - 1.0


def simulate_path(amount, age, gender, state, equity_returns,
                  rate_cache, inflation=DEFAULT_INFLATION, joint_age=None,
                  collect_rows=True, upper_bound=None, lower_bound=None,
                  interest_path=None):
    """Run one withdrawal path.

    equity_returns is a decimal-fraction array of length N (one per year).
    inflation is either a single constant decimal fraction applied every year, or
    a length-N array of per-year inflation (dynamic mode); it is used to express
    withdrawals/balances in today's dollars. interest_path, if given, is a
    length-N array of per-year annuity discount rates -- each year's payout is
    priced at that rate (dynamic mode); when None the rate cache's fixed rate is
    used. Returns a dict with payout/balance arrays and summary totals; set
    collect_rows=False to skip the per-year detail dicts when running many Monte
    Carlo paths.

    upper_bound / lower_bound, if given, cap and floor the annual withdrawal in
    today's dollars at that factor of year 1's withdrawal (e.g. upper_bound=1.2
    caps any later year at 120% of the year-1 real withdrawal). The clamp is
    applied to the actual cash withdrawn, so it feeds back into the balance.
    """
    years = len(equity_returns)
    has_joint = joint_age is not None

    # inflation may be a scalar (constant) or a per-year array (dynamic).
    infl_arr = np.asarray(inflation, dtype=float)
    if infl_arr.ndim == 0:
        infl_arr = np.full(years, float(inflation))

    balance = float(amount)
    cum_infl = 1.0
    cap_real = None
    floor_real = None
    rows = []
    payouts_nominal = np.empty(years)
    payouts_real = np.empty(years)

    for t in range(years):
        cur_age = age + t
        cur_joint = (joint_age + t) if has_joint else None
        rate = None if interest_path is None else float(interest_path[t])
        monthly = balance * rate_cache.monthly_rate(cur_age, cur_joint, rate)
        annual_withdrawal = 12.0 * monthly

        eq = float(equity_returns[t])
        infl = float(infl_arr[t])
        cum_infl *= (1.0 + infl)

        # Optional cap/floor in today's dollars, anchored to year 1's withdrawal.
        real_withdrawal = annual_withdrawal / cum_infl
        if t == 0:
            if upper_bound is not None:
                cap_real = upper_bound * real_withdrawal
            if lower_bound is not None:
                floor_real = lower_bound * real_withdrawal
        if cap_real is not None and real_withdrawal > cap_real:
            real_withdrawal = cap_real
            annual_withdrawal = real_withdrawal * cum_infl
        elif floor_real is not None and real_withdrawal < floor_real:
            real_withdrawal = floor_real
            annual_withdrawal = real_withdrawal * cum_infl

        balance_start = balance
        balance = (balance - annual_withdrawal) * (1.0 + eq)

        # Payout is reported as the annual amount (monthly x 12).
        payouts_nominal[t] = annual_withdrawal
        payouts_real[t] = real_withdrawal
        if collect_rows:
            rows.append({
                "year": t + 1,
                "age": cur_age,
                "balance_start": balance_start,
                "payout": annual_withdrawal,
                "payout_real": real_withdrawal,
                "equity_return": eq,
                "inflation": infl,
                "rate": rate,
                "balance_end": balance,
                "balance_end_real": balance / cum_infl,
            })

    return {
        "rows": rows,
        "ending_balance": balance,
        "ending_balance_real": balance / cum_infl,
        "cum_inflation_factor": cum_infl,
        "payouts_nominal": payouts_nominal,
        "payouts_real": payouts_real,
    }


def _print_report(result, model_summary):
    print(model_summary)
    print()
    rows = result["rows"]
    has_rate = bool(rows) and rows[0].get("rate") is not None
    rate_h = f"{'Rate':>6} " if has_rate else ""
    hdr = (f"{'Yr':>2} {'Age':>3} {'Balance start':>15} "
           f"{'Annual':>14} "
           f"{'Equity':>7} {'CPI':>6} {rate_h}{'Balance end':>15}")
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        rate_c = f"{r['rate']:>6.1%} " if has_rate else ""
        print(f"{r['year']:>2} {r['age']:>3} {r['balance_start']:>15,.0f} "
              f"{r['payout']:>14,.0f} "
              f"{r['equity_return']:>+7.1%} {r['inflation']:>+6.1%} "
              f"{rate_c}{r['balance_end']:>15,.0f}")
    print()
    print(f"Ending balance (nominal):     ${result['ending_balance']:>15,.0f}")
    print(f"Cumulative inflation factor:   {result['cum_inflation_factor']:>15.2f}x")
    print("(all dollar figures are nominal)")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Project 30 years of annuity-equivalent withdrawals from an "
        "equity-invested account (one random path)."
    )
    p.add_argument("amount", type=annuity_quote._normalize_amount,
                   help="starting amount invested, e.g. 1000000 or 1,000,000")
    p.add_argument("age", type=annuity_quote._check_age, help="age today (40-90)")
    p.add_argument("gender", type=annuity_quote._normalize_gender,
                   help="M/F (or male/female)")
    p.add_argument("state", type=annuity_quote._normalize_state,
                   help="2-letter US state code, e.g. FL (only used with --quotes site)")
    p.add_argument("--joint-age", type=annuity_quote._check_age, default=None,
                   help="optional joint beneficiary age (40-90)")
    p.add_argument("--joint-gender", type=annuity_quote._normalize_gender,
                   default=None, help="optional joint beneficiary gender (M/F)")
    p.add_argument("--years", type=int, default=30, help="years to project (default 30)")
    p.add_argument("--inflation", type=float, default=DEFAULT_INFLATION,
                   help="constant annual inflation rate as a decimal fraction, "
                        f"e.g. 0.025 for 2.5 percent (default {DEFAULT_INFLATION})")
    p.add_argument("--model", choices=("bootstrap", "block", "lognormal"),
                   default="bootstrap", help="equity model (default bootstrap)")
    p.add_argument("--block-length", type=int, default=5,
                   help="block size in years for --model block (default 5)")
    p.add_argument("--quotes", choices=("local", "site"), default=DEFAULT_QUOTES,
                   help="annuity pricing source: local SOA-table model (offline, "
                        f"default) or live immediateannuities.com (default {DEFAULT_QUOTES})")
    p.add_argument("--interest", type=float, default=annuity_pricing.DEFAULT_INTEREST,
                   help="flat interest rate for --quotes local "
                        f"(default {annuity_pricing.DEFAULT_INTEREST})")
    p.add_argument("--improvement", action="store_true",
                   help="apply Scale G2 mortality improvement (--quotes local only)")
    p.add_argument("--quote-year", type=int, default=None,
                   help="year to project mortality to for --improvement (default: current)")
    p.add_argument("--dynamic-rates", action="store_true",
                   help="dynamic mode: use the per-year sampled inflation directly "
                        "and evolve the annuity discount rate with it via the "
                        "error-correction model in rate_model.py (local pricing only; "
                        "ignores --inflation and --interest)")
    p.add_argument("--initial-rate", type=float, default=rate_model.DEFAULT_INITIAL_RATE,
                   help="starting 10-year rate for --dynamic-rates "
                        f"(default {rate_model.DEFAULT_INITIAL_RATE})")
    p.add_argument("--upper-bound", type=float, default=None,
                   help="cap annual withdrawal at this factor of year-1's "
                        "withdrawal, in today's dollars (e.g. 1.2)")
    p.add_argument("--lower-bound", type=float, default=None,
                   help="floor annual withdrawal at this factor of year-1's "
                        "withdrawal, in today's dollars (e.g. 0.5)")
    p.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    args = p.parse_args(argv)

    if (args.joint_age is None) != (args.joint_gender is None):
        p.error("--joint-age and --joint-gender must be given together")
    if args.upper_bound is not None and args.upper_bound <= 0:
        p.error("--upper-bound must be positive")
    if args.lower_bound is not None and args.lower_bound < 0:
        p.error("--lower-bound must not be negative")
    if (args.upper_bound is not None and args.lower_bound is not None
            and args.lower_bound > args.upper_bound):
        p.error("--lower-bound must not exceed --upper-bound")
    if args.inflation <= -1:
        p.error("--inflation must be greater than -1 (i.e. > -100%)")
    if args.dynamic_rates and args.quotes != "local":
        p.error("--dynamic-rates requires --quotes local")

    model = JointReturnModel(args.model, block_length=args.block_length)
    rng = np.random.default_rng(args.seed)
    equity, sampled_inflation = model.sample_path(args.years, rng)

    if args.dynamic_rates:
        # Use the sampled inflation directly (no restatement); evolve the rate.
        inflation = sampled_inflation
        irm = rate_model.InterestRateModel(initial_rate=args.initial_rate)
        interest_path = irm.sample_path(sampled_inflation, rng)
    else:
        equity = restate_equity_at_inflation(equity, sampled_inflation, args.inflation)
        inflation = args.inflation
        interest_path = None

    try:
        rate_cache = build_rate_cache(
            args.gender, args.state, args.joint_gender,
            source=args.quotes, interest_rate=args.interest,
            improvement=args.improvement, quote_year=args.quote_year)
        result = simulate_path(
            amount=args.amount, age=args.age, gender=args.gender, state=args.state,
            equity_returns=equity, inflation=inflation,
            rate_cache=rate_cache, joint_age=args.joint_age,
            upper_bound=args.upper_bound, lower_bound=args.lower_bound,
            interest_path=interest_path,
        )
    except (annuity_quote.QuoteError, urllib.error.URLError,
            FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_report(result, model.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
