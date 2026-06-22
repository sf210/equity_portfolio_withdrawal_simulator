#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Monte Carlo confidence intervals for the annuity-equivalent withdrawal model.

Runs many random paths of withdrawal_projection.simulate_path (default 500) and
reports, for both the ending balance and the yearly payout (annual = monthly x
12), the mean, median, and the 80% / 90% / 95% / 99% confidence intervals.

A "C% confidence interval" here is the central interval covering C% of the
simulated outcomes, i.e. the [(100-C)/2, 100-(100-C)/2] percentile range:
  80% -> [10th, 90th]   90% -> [5th, 95th]
  95% -> [2.5th, 97.5th]  99% -> [0.5th, 99.5th]

The annuity-rate cache is built once and reused across every path, so total
network traffic stays at ~one quote per age regardless of the number of sims.

Examples:
    python montecarlo.py 1000000 65 M FL
    python montecarlo.py 1000000 65 M FL --sims 2000 --model block --seed 1
    python montecarlo.py 1000000 65 M FL --joint-age 63 --joint-gender F --nominal
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error

import numpy as np

import annuity_quote
import withdrawal_projection as wp
from equity_model import JointReturnModel

# confidence level -> (lower percentile, upper percentile)
CI_BANDS = {
    80: (10.0, 90.0),
    90: (5.0, 95.0),
    95: (2.5, 97.5),
    99: (0.5, 99.5),
}


def summarize(values: np.ndarray) -> dict:
    """Mean, median, and the central CI bounds for a 1-D array of outcomes."""
    out = {"mean": float(values.mean()), "median": float(np.median(values))}
    for level, (lo, hi) in CI_BANDS.items():
        out[level] = (float(np.percentile(values, lo)),
                      float(np.percentile(values, hi)))
    return out


def run(amount, age, gender, state, joint_age, joint_gender,
        sims, years, model, block_length, seed):
    """Run `sims` paths; return (ending_nominal, ending_real, payouts) arrays.

    payouts has shape (sims, years).
    """
    rng = np.random.default_rng(seed)
    jrm = JointReturnModel(model, block_length=block_length)

    # Warm the rate cache up front: one network quote per distinct age.
    rate_cache = wp.build_rate_cache(
        gender, state, joint_gender, prefetch_from_age=age, years=years
    )

    ending_nominal = np.empty(sims)
    ending_real = np.empty(sims)
    payouts_real = np.empty((sims, years))
    payouts_nominal = np.empty((sims, years))

    for i in range(sims):
        equity, inflation = jrm.sample_path(years, rng)
        res = wp.simulate_path(
            amount=amount, age=age, gender=gender, state=state,
            equity_returns=equity, inflation_rates=inflation,
            rate_cache=rate_cache, joint_age=joint_age, collect_rows=False,
        )
        ending_nominal[i] = res["ending_balance"]
        ending_real[i] = res["ending_balance_real"]
        payouts_real[i] = res["payouts_real"]
        payouts_nominal[i] = res["payouts_nominal"]

    return jrm, ending_nominal, ending_real, payouts_nominal, payouts_real


def _print_balance_block(title, values):
    s = summarize(values)
    print(title)
    print(f"  mean       ${s['mean']:>14,.0f}")
    print(f"  median     ${s['median']:>14,.0f}")
    for level in (80, 90, 95, 99):
        lo, hi = s[level]
        print(f"  {level}% CI     ${lo:>14,.0f}  -  ${hi:>14,.0f}")


def _print_payout_table(title, payouts, age, joint_age):
    # payouts shape (sims, years); summarize each year (column).
    years = payouts.shape[1]
    print(title)
    hdr = (f"{'Yr':>2} {'Age':>3} {'Mean':>11} {'Median':>11} "
           f"{'80% CI':>23} {'90% CI':>23} {'95% CI':>23} {'99% CI':>23}")
    print(hdr)
    print("-" * len(hdr))
    for t in range(years):
        s = summarize(payouts[:, t])
        bands = " ".join(
            f"{s[lvl][0]:>10,.0f}-{s[lvl][1]:<11,.0f}" for lvl in (80, 90, 95, 99)
        )
        print(f"{t+1:>2} {age+t:>3} {s['mean']:>11,.0f} {s['median']:>11,.0f} {bands}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Monte Carlo confidence intervals for the annuity-equivalent "
        "withdrawal projection."
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
    p.add_argument("--sims", type=int, default=500,
                   help="number of simulated paths (default 500)")
    p.add_argument("--years", type=int, default=30, help="years to project (default 30)")
    p.add_argument("--model", choices=("bootstrap", "block", "lognormal"),
                   default="bootstrap", help="equity/inflation model (default bootstrap)")
    p.add_argument("--block-length", type=int, default=5,
                   help="block size in years for --model block (default 5)")
    p.add_argument("--nominal", action="store_true",
                   help="show the payout table in nominal dollars (default: today's $)")
    p.add_argument("--seed", type=int, default=None, help="RNG seed for reproducibility")
    args = p.parse_args(argv)

    if (args.joint_age is None) != (args.joint_gender is None):
        p.error("--joint-age and --joint-gender must be given together")
    if args.sims < 2:
        p.error("--sims must be at least 2")

    t0 = time.time()
    try:
        jrm, end_nom, end_real, pay_nom, pay_real = run(
            amount=args.amount, age=args.age, gender=args.gender, state=args.state,
            joint_age=args.joint_age, joint_gender=args.joint_gender,
            sims=args.sims, years=args.years, model=args.model,
            block_length=args.block_length, seed=args.seed,
        )
    except (annuity_quote.QuoteError, urllib.error.URLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    elapsed = time.time() - t0

    print(jrm.summary())
    print(f"\n{args.sims:,} simulations x {args.years} years  "
          f"(amount ${args.amount:,}, age {args.age} {args.gender}, {args.state}"
          + (f", joint {args.joint_age} {args.joint_gender}" if args.joint_age else "")
          + f")   [{elapsed:.1f}s]\n")

    _print_balance_block("Ending balance - today's dollars", end_real)
    print()
    _print_balance_block("Ending balance - nominal dollars", end_nom)
    print()

    # Practical downside readouts (cheap and relevant to depletion risk).
    pct_below_start = 100.0 * np.mean(end_real < args.amount)
    pct_below_half = 100.0 * np.mean(end_real < args.amount * 0.5)
    print(f"Paths ending below starting amount (real): {pct_below_start:.1f}%   "
          f"below half of it: {pct_below_half:.1f}%\n")

    if args.nominal:
        _print_payout_table("Annual payout by year - nominal dollars",
                            pay_nom, args.age, args.joint_age)
    else:
        _print_payout_table("Annual payout by year - today's dollars",
                            pay_real, args.age, args.joint_age)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
