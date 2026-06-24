#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Price a single-premium immediate annuity (SPIA) from a mortality table.

This is a self-contained actuarial calculation -- no network, no third-party
quote -- intended as a transparent stand-in for the immediateannuities.com
lookup used elsewhere in this project.

Method
------
A SPIA converts a lump sum (premium) into a level lifetime income. With a flat
interest rate i and survival probabilities from a mortality table, the actuarial
present value of $1 per year of income (paid monthly, in arrears, while alive) is

    a_x^(12) ~= a_x + 11/24                     (Woolhouse 2-term, m = 12)
    a_x      = sum_{t>=1} v^t * tpx             (annual annuity-immediate)
    v        = 1 / (1 + i),  tpx = P(life aged x survives t years)

The premium buys income at that "price", so the level annual payout is

    annual_payout = premium / a_x^(12)

For two lives we price a *last-survivor* annuity, which pays as long as EITHER
person is alive. Its factor follows from the inclusion-exclusion identity

    a_LS = a_x + a_y - a_xy           (a_xy = joint annuity, pays while BOTH live)

with the same +11/24 monthly adjustment. Lives are assumed independent.

Mortality tables
----------------
soa_mortality_2581.csv (male) and soa_mortality_2582.csv (female) are the SOA
2012 IAM tables: one annual mortality rate q_x per integer age 0..120. These are
*annuitant* tables (annuitants are healthier than the general population) and are
the basic period rates, as of 2012.

--improvement projects those rates forward generationally using Projection Scale
G2 (soa_mortality_2583.csv male / 2584.csv female, an age,d table where d is the
annual improvement rate):

    q_a(year) = q_a(2012) * (1 - g2_a) ** (year - 2012)

applied as each cohort ages, so the calendar year at attained age a is
quote_year + (a - start_age). Improvement lengthens lifespans and therefore
*lowers* the payout. There is still no expense, profit, or interest-rate load
that a real insurer builds into a quote, so the priced payout remains a clean
actuarial benchmark; see --compare for how it lines up with the live site.

Examples
--------
    python annuity_pricing.py 100000 65 M
    python annuity_pricing.py 100000 65 M --joint-age 63 --joint-gender F
    python annuity_pricing.py 100000 70 F --interest 0.04
    python annuity_pricing.py 100000 65 M --improvement
    python annuity_pricing.py --compare --improvement   # benchmark vs the site
"""

from __future__ import annotations

import argparse
import csv
import datetime
import functools
import os
import re
import sys

DEFAULT_INTEREST = 0.035
PAYMENTS_PER_YEAR = 12  # monthly income, matching immediateannuities.com
# Woolhouse 2-term adjustment from annual annuity-immediate to m-thly: (m-1)/(2m).
_WOOLHOUSE_ADJ = (PAYMENTS_PER_YEAR - 1) / (2 * PAYMENTS_PER_YEAR)

BASE_YEAR = 2012  # the 2012 IAM base rates are as of this calendar year.

_HERE = os.path.dirname(os.path.abspath(__file__))
MORTALITY_FILES = {
    "M": os.path.join(_HERE, "soa_mortality_2581.csv"),
    "F": os.path.join(_HERE, "soa_mortality_2582.csv"),
}
# SOA Projection Scale G2 (annual mortality-improvement rates), same age,d format.
G2_FILES = {
    "M": os.path.join(_HERE, "soa_mortality_2583.csv"),
    "F": os.path.join(_HERE, "soa_mortality_2584.csv"),
}


def _load_age_d(path: str) -> dict[int, float]:
    """Load an age,d CSV into {age: d}."""
    out: dict[int, float] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            out[int(row["age"])] = float(row["d"])
    return out


@functools.lru_cache(maxsize=None)
def load_qx(gender: str) -> dict[int, float]:
    """Load {age: annual mortality rate q_x} for 'M' or 'F'."""
    return _load_age_d(MORTALITY_FILES[gender])


@functools.lru_cache(maxsize=None)
def load_g2(gender: str) -> dict[int, float]:
    """Load {age: annual mortality-improvement rate} from the Scale G2 table.

    Raises FileNotFoundError with a pointed message if the G2 CSV is absent.
    """
    path = G2_FILES[gender]
    if not os.path.exists(path):
        table = "2583" if gender == "M" else "2584"
        raise FileNotFoundError(
            f"--improvement needs the Scale G2 table {os.path.basename(path)} "
            f"(SOA table {table}, age,d format) in {_HERE}; not found"
        )
    return _load_age_d(path)


def survival_curve(qx: dict[int, float], age: int,
                   g2: dict[int, float] | None = None,
                   quote_year: int | None = None) -> list[float]:
    """Survival probabilities tpx for t = 0, 1, 2, ... for a life now aged `age`.

    tp[t] is the probability of surviving t whole years. The table's final age is
    treated as certain death (q = 1) so the curve terminates cleanly: the last
    nonzero entry is being alive at the table's top age.

    When `g2` (a Scale G2 improvement table) and `quote_year` are given, the base
    2012 rates are projected *generationally*: the rate at attained age a, reached
    in calendar year quote_year + (a - age), is

        q_a(year) = q_a(2012) * (1 - g2_a) ** (year - 2012)
    """
    max_age = max(qx)
    tp = [1.0]
    p = 1.0
    a = age
    while a <= max_age:
        if a >= max_age:
            q = 1.0
        else:
            q = qx[a]
            if g2 is not None:
                expo = (quote_year - BASE_YEAR) + (a - age)
                # Scale G2 grades to 0 by its terminal age; ages beyond the G2
                # table simply get no further improvement.
                q *= (1.0 - g2.get(a, 0.0)) ** expo
        p *= (1.0 - q)
        tp.append(p)
        a += 1
    return tp


def _annuity_immediate(tp: list[float], i: float) -> float:
    """APV of $1/yr paid at each year-end while alive (annual annuity-immediate)."""
    v = 1.0 / (1.0 + i)
    return sum(v ** t * tp[t] for t in range(1, len(tp)))


def _joint_immediate(tpx: list[float], tpy: list[float], i: float) -> float:
    """APV of $1/yr paid at year-end while BOTH lives survive (independent lives)."""
    v = 1.0 / (1.0 + i)
    n = min(len(tpx), len(tpy))
    return sum(v ** t * tpx[t] * tpy[t] for t in range(1, n))


def _monthly_factor(annual_immediate: float) -> float:
    """Convert an annual annuity-immediate factor to a monthly one (Woolhouse)."""
    return annual_immediate + _WOOLHOUSE_ADJ


def _resolve_year(quote_year: int | None) -> int:
    return quote_year if quote_year is not None else datetime.date.today().year


def _life_survival(age: int, gender: str, improvement: bool,
                   quote_year: int) -> list[float]:
    """Survival curve for one life, optionally Scale-G2-projected to quote_year."""
    g2 = load_g2(gender) if improvement else None
    return survival_curve(load_qx(gender), age, g2, quote_year)


def single_life_annuity(amount: float, age: int, gender: str,
                        interest_rate: float = DEFAULT_INTEREST,
                        improvement: bool = False,
                        quote_year: int | None = None) -> float:
    """Level annual payout a single-life SPIA of `amount` buys for one life.

    Income is paid monthly in arrears; the return value is the *annual* total
    (12 monthly payments). With improvement=True, the base 2012 IAM rates are
    projected generationally by Scale G2 to `quote_year` (default: this year).
    """
    tp = _life_survival(age, gender, improvement, _resolve_year(quote_year))
    factor = _monthly_factor(_annuity_immediate(tp, interest_rate))
    return amount / factor


def last_survivor_annuity(amount: float, age1: int, gender1: str,
                          age2: int, gender2: str,
                          interest_rate: float = DEFAULT_INTEREST,
                          improvement: bool = False,
                          quote_year: int | None = None) -> float:
    """Level annual payout a last-survivor SPIA of `amount` buys for two lives.

    Pays as long as either person is alive (joint & 100% survivor). Income is
    paid monthly in arrears; the return value is the *annual* total. With
    improvement=True, both lives' base rates are Scale-G2-projected to quote_year.
    """
    year = _resolve_year(quote_year)
    tpx = _life_survival(age1, gender1, improvement, year)
    tpy = _life_survival(age2, gender2, improvement, year)
    ax = _annuity_immediate(tpx, interest_rate)
    ay = _annuity_immediate(tpy, interest_rate)
    axy = _joint_immediate(tpx, tpy, interest_rate)
    factor = _monthly_factor(ax + ay - axy)
    return amount / factor


# --------------------------------------------------------------------------- #
# Comparison harness: model payout vs a live immediateannuities.com quote.
# --------------------------------------------------------------------------- #

def _site_annual(amount, age, gender, state, joint_age=None, joint_gender=None):
    """Fetch a live monthly quote and return it as an annual figure, or None."""
    import annuity_quote
    try:
        monthly = annuity_quote.get_life_quote(
            amount=amount, age=age, gender=gender, state=state,
            joint_age=joint_age, joint_gender=joint_gender,
        )
    except Exception as exc:  # noqa: BLE001 -- report and continue the table
        print(f"  (site fetch failed for age {age} {gender}"
              + (f"/{joint_gender}" if joint_gender else "")
              + f": {exc})", file=sys.stderr)
        return None
    return 12 * int(re.sub(r"[$,]", "", monthly))


def run_comparison(amount=100_000, state="FL", interest=DEFAULT_INTEREST,
                   improvement=False, quote_year=None,
                   ages=(60, 65, 70, 80)) -> int:
    """Print model vs site annual payouts for single and joint annuities."""
    year = _resolve_year(quote_year)
    basis = (f"Scale G2 generational to {year}" if improvement
             else "basic table, no improvement")
    print(f"SPIA annual payout on ${amount:,} premium   "
          f"(interest {interest:.2%}, state {state}, payments monthly)")
    print(f"Model = SOA 2012 IAM, {basis}; no expense/profit load.\n")
    hdr = (f"{'Age':>3} {'Annuitant':<13} {'Model $/yr':>11} "
           f"{'Site $/yr':>10} {'Model/Site':>10}")
    print(hdr)
    print("-" * len(hdr))

    def line(age, label, model_annual, site_annual):
        ratio = (f"{model_annual / site_annual:>9.1%}"
                 if site_annual else f"{'n/a':>10}")
        site = f"{site_annual:>10,.0f}" if site_annual else f"{'n/a':>10}"
        print(f"{age:>3} {label:<13} {model_annual:>11,.0f} {site} {ratio}")

    for age in ages:
        for gender, label in (("M", "single male"), ("F", "single female")):
            model = single_life_annuity(amount, age, gender, interest,
                                        improvement, year)
            site = _site_annual(amount, age, gender, state)
            line(age, label, model, site)
        # Joint: male & female, both this age, last survivor.
        model = last_survivor_annuity(amount, age, "M", age, "F", interest,
                                      improvement, year)
        site = _site_annual(amount, age, "M", state,
                            joint_age=age, joint_gender="F")
        line(age, "joint M&F", model, site)
        print()
    return 0


def _gender(value: str) -> str:
    v = value.strip().upper()
    if v in ("M", "MALE"):
        return "M"
    if v in ("F", "FEMALE"):
        return "F"
    raise argparse.ArgumentTypeError(f"gender must be M/F, got {value!r}")


def _amount(value: str) -> float:
    cleaned = re.sub(r"[\s$,]", "", str(value))
    try:
        amt = float(cleaned)
    except ValueError:
        raise argparse.ArgumentTypeError(f"amount must be a number, got {value!r}")
    if amt <= 0:
        raise argparse.ArgumentTypeError("amount must be positive")
    return amt


def _age(value: str) -> int:
    try:
        age = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"age must be an integer, got {value!r}")
    if not 0 <= age <= 120:
        raise argparse.ArgumentTypeError("age must be between 0 and 120")
    return age


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Price a single-premium immediate annuity from the SOA 2012 "
        "IAM mortality tables."
    )
    p.add_argument("amount", type=_amount, nargs="?",
                   help="premium / starting investment, e.g. 100000")
    p.add_argument("age", type=_age, nargs="?", help="age today (0-120)")
    p.add_argument("gender", type=_gender, nargs="?", help="M/F")
    p.add_argument("--joint-age", type=_age, default=None,
                   help="second life's age, for a last-survivor annuity")
    p.add_argument("--joint-gender", type=_gender, default=None,
                   help="second life's gender (M/F)")
    p.add_argument("--interest", type=float, default=DEFAULT_INTEREST,
                   help=f"flat annual interest rate (default {DEFAULT_INTEREST})")
    p.add_argument("--improvement", action="store_true",
                   help="project the 2012 base rates generationally with Scale G2 "
                        "to the quote year (needs the G2 CSV tables)")
    p.add_argument("--quote-year", type=int, default=None,
                   help="calendar year to project mortality to for --improvement "
                        "(default: current year)")
    p.add_argument("--compare", action="store_true",
                   help="benchmark model payouts against live immediateannuities.com "
                        "quotes for ages 60/65/70/80 (ignores positional args)")
    p.add_argument("--state", default="FL",
                   help="US state for --compare site quotes (default FL)")
    args = p.parse_args(argv)

    if args.compare:
        return run_comparison(state=args.state, interest=args.interest,
                              improvement=args.improvement,
                              quote_year=args.quote_year)

    if args.amount is None or args.age is None or args.gender is None:
        p.error("amount, age, and gender are required (or use --compare)")
    if (args.joint_age is None) != (args.joint_gender is None):
        p.error("--joint-age and --joint-gender must be given together")
    if args.interest <= -1:
        p.error("--interest must be greater than -1")

    try:
        if args.joint_age is not None:
            annual = last_survivor_annuity(
                args.amount, args.age, args.gender,
                args.joint_age, args.joint_gender, args.interest,
                args.improvement, args.quote_year)
            who = (f"last-survivor {args.age}{args.gender} & "
                   f"{args.joint_age}{args.joint_gender}")
        else:
            annual = single_life_annuity(
                args.amount, args.age, args.gender, args.interest,
                args.improvement, args.quote_year)
            who = f"single life {args.age}{args.gender}"
    except FileNotFoundError as exc:
        p.error(str(exc))

    basis = (f", Scale G2 to {_resolve_year(args.quote_year)}"
             if args.improvement else "")
    rate = annual / args.amount
    print(f"{who}   premium ${args.amount:,.0f}   "
          f"interest {args.interest:.2%}{basis}")
    print(f"  annual payout : ${annual:,.0f}   ({rate:.2%} of premium)")
    print(f"  monthly payout: ${annual / 12:,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
