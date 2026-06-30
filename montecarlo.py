#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Monte Carlo percentile report for the annuity-equivalent withdrawal model.

Runs many random paths of withdrawal_projection.simulate_path (default 5000) and
reports, in both today's (real) and nominal dollars, a summary table (ending
balance, total return as an annualized geometric mean, and the mean annual
withdrawal) and a per-year withdrawal table -- each across the 1st / 5th / 25th /
median / 75th / 95th / 99th percentiles of the simulated outcomes. This matches
the web front end (webapp/app.py) exactly. The withdrawal figures are reported in
today's dollars (deflated by cumulative inflation).

The summary also reports the worst single-year and worst cumulative 5-year *real*
(inflation-adjusted) equity total return seen anywhere in the simulation.

Annuity payouts are priced by default from the local SOA-table model
(annuity_pricing, offline); --quotes site uses live immediateannuities.com
quotes instead. Either way the rate cache is built once and reused across every
path, so pricing cost (and any network traffic) stays at ~one rate per age
regardless of the number of sims.

When run interactively, after printing the report it offers to save the output to
a PDF or CSV file.

Examples:
    python montecarlo.py 1000000 65 M FL
    python montecarlo.py 1000000 65 M FL --interest 0.04 --improvement
    python montecarlo.py 1000000 65 M FL --quotes site --sims 2000 --seed 1
    python montecarlo.py 1000000 65 M FL --joint-age 63 --joint-gender F \
        --upper-bound 1.2 --lower-bound 0.5
"""

from __future__ import annotations

import argparse
import csv
import getpass
import sys
import time
import urllib.error
from datetime import datetime

import numpy as np

import annuity_pricing
import annuity_quote
import rate_model
import withdrawal_projection as wp
from equity_model import JointReturnModel

# Percentiles shown throughout the report (mirrors webapp/app.py and figures.py).
PCTS = [1, 5, 25, 50, 75, 95, 99]
PCT_HEADERS = ["1st", "5th", "25th", "Median", "75th", "95th", "99th"]

# Text-table column widths: the row-label column and each percentile column.
_LABEL_W = 24
_COL_W = 11


def _pcts(arr: np.ndarray) -> list:
    """The PCTS percentiles of a 1-D outcome array, as plain floats."""
    return [float(np.percentile(arr, p)) for p in PCTS]


def _money(v: float) -> str:
    """Compact dollar label, e.g. $1.24M / $930k / $0 (matches the web)."""
    a = abs(v)
    if a >= 1e6:
        return f"${v / 1e6:,.2f}M"
    if a >= 1e3:
        return f"${v / 1e3:,.0f}k"
    return f"${v:,.0f}"


def _pct_str(frac: float, decimals: int = 0) -> str:
    return f"{frac * 100:,.{decimals}f}%"


def run(amount, age, gender, state, joint_age, joint_gender,
        sims, years, model, block_length, seed,
        inflation=wp.DEFAULT_INFLATION, upper_bound=None, lower_bound=None,
        quotes=wp.DEFAULT_QUOTES, interest=annuity_pricing.DEFAULT_INTEREST,
        improvement=False, quote_year=None,
        dynamic_rates=False, initial_rate=rate_model.DEFAULT_INITIAL_RATE):
    """Run `sims` paths.

    In the default (constant) mode, inflation is a constant decimal fraction used
    to deflate results to today's dollars, and the annuity discount rate is fixed
    (interest / quotes / improvement / quote_year select the pricing source).

    With dynamic_rates=True, each path uses its own per-year sampled inflation
    (no restatement of equity) and an annuity discount rate that evolves with it
    via rate_model.InterestRateModel, starting from initial_rate (local pricing).

    Returns (jrm, ending_nominal, ending_real, payouts_nominal, payouts_real,
    equities, inflations, balances_real, interests) with the per-year arrays
    shaped (sims, years); inflations holds the per-year inflation actually used to
    deflate each path, balances_real the end-of-year balance in today's dollars,
    and interests the per-year annuity discount rate (the fixed rate in static
    local mode, NaN for static site quotes, the evolving rate when dynamic).
    """
    rng = np.random.default_rng(seed)
    jrm = JointReturnModel(model, block_length=block_length)

    # Warm the rate cache up front: one priced/quoted rate per distinct age.
    rate_cache = wp.build_rate_cache(
        gender, state, joint_gender, prefetch_from_age=age, years=years,
        source=quotes, interest_rate=interest, improvement=improvement,
        quote_year=quote_year,
    )
    irm = (rate_model.InterestRateModel(initial_rate=initial_rate)
           if dynamic_rates else None)

    # The per-year discount rate actually used: the fixed local rate in static
    # mode, NaN when static site quotes (no single rate), evolving when dynamic.
    if dynamic_rates:
        static_rate = None
    elif quotes == "local":
        static_rate = interest
    else:
        static_rate = float("nan")

    ending_nominal = np.empty(sims)
    ending_real = np.empty(sims)
    payouts_real = np.empty((sims, years))
    payouts_nominal = np.empty((sims, years))
    equities = np.empty((sims, years))
    inflations = np.empty((sims, years))
    balances_real = np.empty((sims, years))
    interests = np.empty((sims, years))

    for i in range(sims):
        equity, sampled_inflation = jrm.sample_path(years, rng)
        if dynamic_rates:
            path_inflation = sampled_inflation
            interest_path = irm.sample_path(sampled_inflation, rng)
        else:
            equity = wp.restate_equity_at_inflation(equity, sampled_inflation, inflation)
            path_inflation = inflation
            interest_path = None
        res = wp.simulate_path(
            amount=amount, age=age, gender=gender, state=state,
            equity_returns=equity, inflation=path_inflation,
            rate_cache=rate_cache, joint_age=joint_age, collect_rows=False,
            upper_bound=upper_bound, lower_bound=lower_bound,
            interest_path=interest_path,
        )
        ending_nominal[i] = res["ending_balance"]
        ending_real[i] = res["ending_balance_real"]
        payouts_real[i] = res["payouts_real"]
        payouts_nominal[i] = res["payouts_nominal"]
        equities[i] = equity
        inflations[i] = sampled_inflation if dynamic_rates else inflation
        balances_real[i] = res["balances_real"]
        interests[i] = interest_path if interest_path is not None else static_rate

    return (jrm, ending_nominal, ending_real, payouts_nominal, payouts_real,
            equities, inflations, balances_real, interests)


def worst_real_returns(equities, inflations, window=5):
    """Worst single-year and worst cumulative `window`-year real equity return.

    The real (inflation-adjusted) one-year return is (1+equity)/(1+inflation)-1.
    Returns (worst_1yr, worst_window) as decimal fractions; worst_window is None
    if fewer than `window` years were projected.
    """
    real = (1.0 + equities) / (1.0 + inflations) - 1.0
    worst_1yr = float(real.min())
    growth = 1.0 + real
    years = growth.shape[1]
    if years >= window:
        ones = np.ones((growth.shape[0], 1))
        pref = np.concatenate([ones, np.cumprod(growth, axis=1)], axis=1)
        # product of returns over each window = ratio of prefix products.
        wprod = pref[:, window:] / pref[:, :years - window + 1]
        worst_window = float(wprod.min()) - 1.0
    else:
        worst_window = None
    return worst_1yr, worst_window


def _pct_table_lines(title, header_cells, rows):
    """Text lines for a percentile table: a label column + the PCTS columns."""
    lines = [title]
    head = " " * _LABEL_W + "".join(f"{h:>{_COL_W}}" for h in header_cells)
    lines.append(head)
    lines.append("-" * len(head))
    for label, cells in rows:
        lines.append(f"{label:<{_LABEL_W}}"
                     + "".join(f"{c:>{_COL_W}}" for c in cells))
    return lines


def _summary_block_lines(title, end_vals, total_returns, wd_vals):
    """One summary block (ending balance, total return, mean withdrawal)."""
    rows = [
        ("Ending balance", [_money(v) for v in _pcts(end_vals)]),
        ("Total return (geo mean)", [_pct_str(v, 1) for v in _pcts(total_returns)]),
        ("Mean annual withdrawal", [_money(v) for v in _pcts(wd_vals)]),
    ]
    return _pct_table_lines(title, PCT_HEADERS, rows)


def _worst_return_lines(worst_1yr, worst_5yr):
    """The worst real single-year / cumulative 5-year equity-return lines."""
    lines = [f"Worst 1-yr real return: {worst_1yr:.1%}"]
    if worst_5yr is not None:
        lines.append(f"Worst 5-yr real return: {worst_5yr:.1%}  (cumulative)")
    return lines


def geo_mean_return(equities, inflations=None):
    """Per-path annualized geometric-mean equity return.

    Real when `inflations` is given (each year's growth is deflated), else
    nominal: prod(growth)**(1/years) - 1 across each path's yearly returns.
    """
    growth = 1.0 + equities
    if inflations is not None:
        growth = growth / (1.0 + inflations)
    return np.prod(growth, axis=1) ** (1.0 / equities.shape[1]) - 1.0


def _payout_table_lines(title, payouts, age):
    """Text lines for the per-year withdrawal table: mean, median, percentiles."""
    years = payouts.shape[1]
    extra = [p for p in PCTS if p != 50]  # median shown in its own column
    headers = (["Yr", "Age", "Mean", "Median"]
               + [("1st" if p == 1 else f"{p}th") for p in extra])
    lines = [title]
    hdr = (f"{headers[0]:>3} {headers[1]:>3} {headers[2]:>10} {headers[3]:>10} "
           + " ".join(f"{h:>10}" for h in headers[4:]))
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for t in range(years):
        col = payouts[:, t]
        cells = " ".join(f"{_money(float(np.percentile(col, p))):>10}"
                         for p in extra)
        lines.append(
            f"{t+1:>3} {age+t:>3} {_money(float(col.mean())):>10} "
            f"{_money(float(np.median(col))):>10} {cells}"
        )
    return lines


# --------------------------------------------------------------------------- #
# File export. The figure-rich PDF lives in report_pdf.py (imported lazily); the
# CSV writer below is self-contained (standard library only).
# --------------------------------------------------------------------------- #

def _summary_csv_rows(end_vals, total_returns, wd_vals):
    """The three summary rows (ending balance, total return, mean withdrawal)."""
    return [
        ["ending balance"] + [round(v) for v in _pcts(end_vals)],
        ["total return (geo mean)"] + [f"{v:.4f}" for v in _pcts(total_returns)],
        ["mean annual withdrawal"] + [round(v) for v in _pcts(wd_vals)],
    ]


def write_csv(path, *, header_line, params_line, end_real, end_nom,
              total_real, total_nom, wd_real, wd_nom,
              worst_1yr, worst_5yr, payout, age):
    """Write the percentile summary (real + nominal) and per-year withdrawals."""
    pct_cols = [f"p{p}" for p in PCTS]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([header_line])
        w.writerow([params_line])
        w.writerow([])
        w.writerow(["Summary - today's dollars (real)"])
        w.writerow(["metric"] + pct_cols)
        for row in _summary_csv_rows(end_real, total_real, wd_real):
            w.writerow(row)
        w.writerow([])
        w.writerow(["Summary - nominal dollars"])
        w.writerow(["metric"] + pct_cols)
        for row in _summary_csv_rows(end_nom, total_nom, wd_nom):
            w.writerow(row)
        w.writerow([])
        w.writerow(["worst 1-yr real return", f"{worst_1yr:.4f}"])
        if worst_5yr is not None:
            w.writerow(["worst 5-yr real return (cumulative)", f"{worst_5yr:.4f}"])
        w.writerow([])
        extra = [p for p in PCTS if p != 50]
        w.writerow(["Annual withdrawal by year - today's dollars (real)"])
        w.writerow(["year", "age", "mean", "median"] + [f"p{p}" for p in extra])
        for t in range(payout.shape[1]):
            col = payout[:, t]
            w.writerow([t + 1, age + t, round(float(col.mean())),
                        round(float(np.median(col)))]
                       + [round(float(np.percentile(col, p))) for p in extra])


def _prompt_and_export(csv_kwargs, report_data):
    """Interactively offer to save the consolidated PDF report or a CSV."""
    if not sys.stdin.isatty():
        return
    while True:
        try:
            choice = input(
                "\nSave output to a file? [PDF / csv / exit]: "
            ).strip().lower()
        except EOFError:
            return
        if choice in ("", "exit", "quit", "q", "e"):
            return
        if choice == "pdf":
            import report_pdf
            path = (input("PDF filename [montecarlo_report.pdf]: ").strip()
                    or "montecarlo_report.pdf")
            report_pdf.write_report_pdf(path, report_data)
            print(f"wrote {path}")
        elif choice == "csv":
            path = (input("CSV filename [montecarlo_report.csv]: ").strip()
                    or "montecarlo_report.csv")
            write_csv(path, **csv_kwargs)
            print(f"wrote {path}")
        else:
            print("Please type PDF, csv, or exit.")


def build_report(amount, age, gender, state, joint_age, joint_gender,
                 sims, years, model, block_length, seed,
                 inflation=wp.DEFAULT_INFLATION, upper_bound=None, lower_bound=None,
                 quotes=wp.DEFAULT_QUOTES, interest=annuity_pricing.DEFAULT_INTEREST,
                 improvement=False, quote_year=None,
                 dynamic_rates=False, initial_rate=rate_model.DEFAULT_INITIAL_RATE):
    """Run the simulation and assemble the report in every output form.

    Returns (report_text, csv_kwargs, report_data):
      report_text -- the stacked-block text report (shown on screen / printed),
      csv_kwargs  -- kwargs ready to splat into write_csv,
      report_data -- dict of raw per-path arrays + labels for the consolidated
                     PDF report (report_pdf.write_report_pdf).
    Raises annuity_quote.QuoteError / urllib.error.URLError (site quotes) or
    FileNotFoundError (--improvement without the G2 tables) on pricing failure.
    """
    # Dynamic rates evolve a US-calibrated annuity discount model from a sampled
    # inflation path; that only makes sense with the US sample (driving it with
    # foreign -- e.g. hyperinflation -- series is meaningless). The global sample
    # always uses the constant-inflation real-restatement path instead.
    if dynamic_rates and model != "us":
        raise ValueError("dynamic rates are only available with the US sample "
                         "(model='us'); the global sample uses constant inflation.")
    t0 = time.time()
    (jrm, end_nom, end_real, pay_nom, pay_real, equities, inflations,
     balances_real, interests) = run(
        amount=amount, age=age, gender=gender, state=state,
        joint_age=joint_age, joint_gender=joint_gender,
        sims=sims, years=years, model=model,
        block_length=block_length, seed=seed,
        inflation=inflation, upper_bound=upper_bound, lower_bound=lower_bound,
        quotes=quotes, interest=interest, improvement=improvement,
        quote_year=quote_year, dynamic_rates=dynamic_rates,
        initial_rate=initial_rate,
    )
    elapsed = time.time() - t0

    worst_1yr, worst_5yr = worst_real_returns(equities, inflations)
    # Per-path distributions for the summary table (percentiles taken below):
    # annualized geometric-mean total return and mean annual withdrawal.
    total_real = geo_mean_return(equities, inflations)
    total_nom = geo_mean_return(equities)
    wd_real = pay_real.mean(axis=1)
    wd_nom = pay_nom.mean(axis=1)

    model_summary = jrm.summary()
    bounds_bits = []
    if upper_bound is not None:
        bounds_bits.append(f"upper {upper_bound:g}x")
    if lower_bound is not None:
        bounds_bits.append(f"lower {lower_bound:g}x")
    bounds_note = f", bounds {'/'.join(bounds_bits)}" if bounds_bits else ""
    if dynamic_rates:
        infl_note = ", inflation dynamic"
        pricing_note = (f", local dynamic rate (i0 {initial_rate:.1%})"
                        + (" +G2" if improvement else ""))
    elif quotes == "site":
        infl_note = f", inflation {inflation:.1%}"
        pricing_note = f", site quotes ({state})"
    else:
        infl_note = f", inflation {inflation:.1%}"
        pricing_note = (f", local @ {interest:.1%}"
                        + (" +G2" if improvement else ""))
    params_line = (
        f"{sims:,} simulations x {years} years  "
        f"(amount ${amount:,}, age {age} {gender}"
        + (f", joint {joint_age} {joint_gender}" if joint_age else "")
        + infl_note
        + pricing_note
        + bounds_note
        + f")   [{elapsed:.1f}s]")

    real_block = _summary_block_lines(
        "Summary - today's dollars (real)", end_real, total_real, wd_real)
    nom_block = _summary_block_lines(
        "Summary - nominal dollars", end_nom, total_nom, wd_nom)
    worst_lines = _worst_return_lines(worst_1yr, worst_5yr)

    pct_below_start = 100.0 * np.mean(end_real < amount)
    pct_below_half = 100.0 * np.mean(end_real < amount * 0.5)
    downside = (f"Paths ending below starting amount (real): {pct_below_start:.1f}%   "
                f"below half of it: {pct_below_half:.1f}%")

    payout_title = "Annual withdrawal by year - today's dollars"
    payout = pay_real
    payout_lines = _payout_table_lines(payout_title, payout, age)

    # ----- stacked text report -----
    report_lines = (
        [model_summary, "", params_line, ""]
        + real_block + [""]
        + nom_block + [""]
        + worst_lines + ["", downside, ""]
        + payout_lines
    )
    report_text = "\n".join(report_lines)

    # ----- export bodies -----
    user = getpass.getuser()
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    footer_text = f"{user}    {stamp}"
    csv_kwargs = dict(
        header_line=footer_text, params_line=params_line,
        end_real=end_real, end_nom=end_nom,
        total_real=total_real, total_nom=total_nom,
        wd_real=wd_real, wd_nom=wd_nom,
        worst_1yr=worst_1yr, worst_5yr=worst_5yr,
        payout=payout, age=age,
    )
    report_data = dict(
        title="Annuity-equivalent Monte Carlo report",
        footer_text=footer_text, params_line=params_line,
        model_summary=model_summary,
        amount=amount, age=age, gender=gender,
        joint_age=joint_age, joint_gender=joint_gender,
        years=years, sims=sims,
        dynamic_rates=dynamic_rates, quotes=quotes,
        end_real=end_real, end_nom=end_nom,
        balances_real=balances_real, payouts_real=pay_real,
        payouts_nominal=pay_nom,
        equities=equities, inflations=inflations, interests=interests,
        worst_1yr=worst_1yr, worst_5yr=worst_5yr,
        downside=downside,
    )
    return report_text, csv_kwargs, report_data


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description="Monte Carlo percentile report for the annuity-equivalent "
        "withdrawal projection."
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
    p.add_argument("--sims", type=int, default=5000,
                   help="number of simulated paths (default 5000)")
    p.add_argument("--years", type=int, default=35, help="years to project (default 35)")
    p.add_argument("--inflation", type=float, default=wp.DEFAULT_INFLATION,
                   help="constant annual inflation rate as a decimal fraction, "
                        f"e.g. 0.025 for 2.5 percent (default {wp.DEFAULT_INFLATION})")
    p.add_argument("--model", choices=("us", "global", "postwar"),
                   default="global", help="equity return sample: 'us' (S&P 500 / "
                   "CPI), 'global' (broad developed markets, JST; default), or "
                   "'postwar' (the global sample restricted to 1950+)")
    p.add_argument("--block-length", type=int, default=5,
                   help="block size in years for the block bootstrap (default 5)")
    p.add_argument("--quotes", choices=("local", "site"), default=wp.DEFAULT_QUOTES,
                   help="annuity pricing source: local SOA-table model (offline, "
                        f"default) or live immediateannuities.com (default {wp.DEFAULT_QUOTES})")
    p.add_argument("--interest", type=float, default=rate_model.DEFAULT_INITIAL_RATE,
                   help="flat interest rate for --quotes local "
                        f"(default {rate_model.DEFAULT_INITIAL_RATE})")
    p.add_argument("--improvement", action=argparse.BooleanOptionalAction,
                   default=True,
                   help="apply Scale G2 mortality improvement (--quotes local "
                        "only; on by default, use --no-improvement to disable)")
    p.add_argument("--quote-year", type=int, default=None,
                   help="year to project mortality to for --improvement (default: current)")
    p.add_argument("--dynamic-rates", action="store_true",
                   help="dynamic mode: per-year sampled inflation drives both the "
                        "deflator and an evolving annuity discount rate "
                        "(local pricing only; ignores --inflation and --interest)")
    p.add_argument("--initial-rate", type=float, default=rate_model.DEFAULT_INITIAL_RATE,
                   help="starting 10-year rate for --dynamic-rates "
                        f"(default {rate_model.DEFAULT_INITIAL_RATE})")
    p.add_argument("--upper-bound", type=float, default=1.5,
                   help="cap annual withdrawal at this factor of year-1's "
                        "withdrawal, in today's dollars (default 1.5)")
    p.add_argument("--lower-bound", type=float, default=None,
                   help="floor annual withdrawal at this factor of year-1's "
                        "withdrawal, in today's dollars (e.g. 0.5)")
    p.add_argument("--seed", type=int, default=42, help="RNG seed for reproducibility")
    args = p.parse_args(argv)

    if (args.joint_age is None) != (args.joint_gender is None):
        p.error("--joint-age and --joint-gender must be given together")
    if args.sims < 2:
        p.error("--sims must be at least 2")
    if args.inflation <= -1:
        p.error("--inflation must be greater than -1 (i.e. > -100%)")
    if args.dynamic_rates and args.quotes != "local":
        p.error("--dynamic-rates requires --quotes local")
    if args.dynamic_rates and args.model != "us":
        p.error("--dynamic-rates requires --model us")
    if args.upper_bound is not None and args.upper_bound <= 0:
        p.error("--upper-bound must be positive")
    if args.lower_bound is not None and args.lower_bound < 0:
        p.error("--lower-bound must not be negative")
    if (args.upper_bound is not None and args.lower_bound is not None
            and args.lower_bound > args.upper_bound):
        p.error("--lower-bound must not exceed --upper-bound")

    try:
        report_text, csv_kwargs, report_data = build_report(
            amount=args.amount, age=args.age, gender=args.gender, state=args.state,
            joint_age=args.joint_age, joint_gender=args.joint_gender,
            sims=args.sims, years=args.years, model=args.model,
            block_length=args.block_length, seed=args.seed,
            inflation=args.inflation,
            upper_bound=args.upper_bound, lower_bound=args.lower_bound,
            quotes=args.quotes, interest=args.interest,
            improvement=args.improvement, quote_year=args.quote_year,
            dynamic_rates=args.dynamic_rates, initial_rate=args.initial_rate,
        )
    except (annuity_quote.QuoteError, urllib.error.URLError,
            FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(report_text)
    _prompt_and_export(csv_kwargs, report_data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
