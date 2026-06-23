#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Project annuity-equivalent withdrawals from an equity-invested account.

Strategy modelled (this is NOT buying an annuity -- it keeps the money invested
in equities and withdraws what a life annuity *would* pay):

  Starting balance = amount invested. For each of N years:
    1. Look up the monthly life-annuity payout for the CURRENT balance at the
       CURRENT age (immediateannuities.com, via annuity_quote.get_life_quote).
       The payout is linear in premium, so we quote a $100k reference once per
       age and scale it -- no per-balance HTTP calls.
    2. Withdraw 12 x that monthly payout from the balance.
    3. Grow the remaining balance by that year's nominal equity return.
    4. Age (and any joint age) increases by 1; repeat.

Equity returns and CPI inflation are drawn jointly (see equity_model) so the
equity/inflation correlation is preserved. Results are reported in nominal
dollars (the Monte Carlo follow-up reports in today's dollars).

Optional --upper-bound / --lower-bound put a cap and floor on the annual
withdrawal, expressed in today's dollars as a factor of year 1's withdrawal:
e.g. with a $50,000 year-1 withdrawal, --upper-bound 1.2 caps any later year at
$60,000 (today's $) and --lower-bound 0.5 floors it at $25,000 (today's $).

The annuity site only quotes ages 40-90, so quote ages above 90 are clamped to
90 (conservative: it understates the rising payout rate at very old ages).

This module exposes build_rate_cache() and simulate_path() for reuse by the
Monte Carlo (many-paths / confidence-interval) follow-up.

Example:
    python withdrawal_projection.py 1000000 65 M FL
    python withdrawal_projection.py 1000000 65 M FL --joint-age 63 --joint-gender F \
        --model lognormal --seed 1
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error

import numpy as np

import annuity_quote
from equity_model import JointReturnModel

REF_PREMIUM = 100_000  # payout is linear in premium; quote this and scale.
SITE_MAX_AGE = 90      # immediateannuities.com dropdown maximum.


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


def build_rate_cache(gender: str, state: str, joint_gender: str | None = None,
                     prefetch_from_age: int | None = None, years: int = 30):
    """Create an AnnuityRateCache, optionally pre-fetching every age it will need.

    Pre-fetching warms the cache with one network call per distinct age up front
    (handy before launching many Monte Carlo paths)."""
    cache = AnnuityRateCache(gender, state, joint_gender)
    if prefetch_from_age is not None:
        has_joint = joint_gender is not None
        for offset in range(years):
            cache.monthly_rate(
                prefetch_from_age + offset,
                (prefetch_from_age + offset) if has_joint else None,
            )
    return cache


def simulate_path(amount, age, gender, state, equity_returns, inflation_rates,
                  rate_cache, joint_age=None, collect_rows=True,
                  upper_bound=None, lower_bound=None):
    """Run one withdrawal path.

    equity_returns / inflation_rates are decimal-fraction arrays of length N
    (one per year). Returns a dict with payout/balance arrays and summary totals;
    set collect_rows=False to skip the per-year detail dicts when running many
    Monte Carlo paths.

    upper_bound / lower_bound, if given, cap and floor the annual withdrawal in
    today's dollars at that factor of year 1's withdrawal (e.g. upper_bound=1.2
    caps any later year at 120% of the year-1 real withdrawal). The clamp is
    applied to the actual cash withdrawn, so it feeds back into the balance.
    """
    years = len(equity_returns)
    has_joint = joint_age is not None

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
        monthly = balance * rate_cache.monthly_rate(cur_age, cur_joint)
        annual_withdrawal = 12.0 * monthly

        eq = float(equity_returns[t])
        infl = float(inflation_rates[t])
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
    hdr = (f"{'Yr':>2} {'Age':>3} {'Balance start':>15} "
           f"{'Annual':>14} "
           f"{'Equity':>7} {'CPI':>6} {'Balance end':>15}")
    print(hdr)
    print("-" * len(hdr))
    for r in result["rows"]:
        print(f"{r['year']:>2} {r['age']:>3} {r['balance_start']:>15,.0f} "
              f"{r['payout']:>14,.0f} "
              f"{r['equity_return']:>+7.1%} {r['inflation']:>+6.1%} "
              f"{r['balance_end']:>15,.0f}")
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
                   help="2-letter US state code, e.g. FL")
    p.add_argument("--joint-age", type=annuity_quote._check_age, default=None,
                   help="optional joint beneficiary age (40-90)")
    p.add_argument("--joint-gender", type=annuity_quote._normalize_gender,
                   default=None, help="optional joint beneficiary gender (M/F)")
    p.add_argument("--years", type=int, default=30, help="years to project (default 30)")
    p.add_argument("--model", choices=("bootstrap", "block", "lognormal"),
                   default="bootstrap", help="equity/inflation model (default bootstrap)")
    p.add_argument("--block-length", type=int, default=5,
                   help="block size in years for --model block (default 5)")
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

    model = JointReturnModel(args.model, block_length=args.block_length)
    rng = np.random.default_rng(args.seed)
    equity, inflation = model.sample_path(args.years, rng)

    try:
        rate_cache = build_rate_cache(args.gender, args.state, args.joint_gender)
        result = simulate_path(
            amount=args.amount, age=args.age, gender=args.gender, state=args.state,
            equity_returns=equity, inflation_rates=inflation,
            rate_cache=rate_cache, joint_age=args.joint_age,
            upper_bound=args.upper_bound, lower_bound=args.lower_bound,
        )
    except (annuity_quote.QuoteError, urllib.error.URLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_report(result, model.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
