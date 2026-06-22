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

The ending-balance (today's dollars) block also reports the worst single-year and
worst cumulative 5-year *real* (inflation-adjusted) equity total return seen
anywhere in the simulation.

The annuity-rate cache is built once and reused across every path, so total
network traffic stays at ~one quote per age regardless of the number of sims.

When run interactively, after printing the report it offers to save the output to
a PDF or CSV file.

Examples:
    python montecarlo.py 1000000 65 M FL
    python montecarlo.py 1000000 65 M FL --sims 2000 --model block --seed 1
    python montecarlo.py 1000000 65 M FL --joint-age 63 --joint-gender F --nominal
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

# Width of one CI band cell as rendered below, "{:>10,.0f}-{:<11,.0f}" = 10+1+11.
_BAND_W = 22


def summarize(values: np.ndarray) -> dict:
    """Mean, median, and the central CI bounds for a 1-D array of outcomes."""
    out = {"mean": float(values.mean()), "median": float(np.median(values))}
    for level, (lo, hi) in CI_BANDS.items():
        out[level] = (float(np.percentile(values, lo)),
                      float(np.percentile(values, hi)))
    return out


def run(amount, age, gender, state, joint_age, joint_gender,
        sims, years, model, block_length, seed):
    """Run `sims` paths.

    Returns (jrm, ending_nominal, ending_real, payouts_nominal, payouts_real,
    equities, inflations). The payout and per-year return arrays have shape
    (sims, years).
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
    equities = np.empty((sims, years))
    inflations = np.empty((sims, years))

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
        equities[i] = equity
        inflations[i] = inflation

    return (jrm, ending_nominal, ending_real, payouts_nominal, payouts_real,
            equities, inflations)


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


def _balance_block_lines(title, values, extras=None):
    """Text lines for one ending-balance summary block."""
    s = summarize(values)
    lines = [
        title,
        f"  mean       ${s['mean']:>14,.0f}",
        f"  median     ${s['median']:>14,.0f}",
    ]
    for level in (80, 90, 95, 99):
        lo, hi = s[level]
        lines.append(f"  {level}% CI     ${lo:>14,.0f}  -  ${hi:>14,.0f}")
    if extras:
        lines.extend(extras)
    return lines


def _worst_return_lines(worst_1yr, worst_5yr):
    """Extra lines (in today's dollars / real terms) for the real balance block."""
    lines = [f"  worst 1-yr real return  {worst_1yr:>7.1%}"]
    if worst_5yr is not None:
        lines.append(f"  worst 5-yr real return  {worst_5yr:>7.1%}  (cumulative)")
    return lines


def _payout_table_lines(title, payouts, age):
    """Text lines for the per-year payout confidence-interval table."""
    years = payouts.shape[1]
    lines = [title]
    hdr = (f"{'Yr':>2} {'Age':>3} {'Mean':>11} {'Median':>11} "
           + " ".join(f"{lbl:^{_BAND_W}}"
                      for lbl in ("80% CI", "90% CI", "95% CI", "99% CI")))
    lines.append(hdr)
    lines.append("-" * len(hdr))
    for t in range(years):
        s = summarize(payouts[:, t])
        bands = " ".join(
            f"{s[lvl][0]:>10,.0f}-{s[lvl][1]:<11,.0f}" for lvl in (80, 90, 95, 99)
        )
        lines.append(
            f"{t+1:>2} {age+t:>3} {s['mean']:>11,.0f} {s['median']:>11,.0f} {bands}"
        )
    return lines


def _side_by_side(left, right, gutter=4):
    """Combine two blocks of lines into single rows, left block padded to width."""
    width = (max((len(ln) for ln in left), default=0)) + gutter
    rows = []
    for i in range(max(len(left), len(right))):
        l = left[i] if i < len(left) else ""
        r = right[i] if i < len(right) else ""
        rows.append(f"{l:<{width}}{r}")
    return rows


# --------------------------------------------------------------------------- #
# File export (PDF / CSV). The PDF writer is self-contained (standard library
# only) and uses the built-in Courier font, which suits the monospaced tables.
# --------------------------------------------------------------------------- #

def _pdf_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _pdf_content_stream(lines, footer, *, x, y_start, leading, size,
                        footer_y, footer_size):
    parts = ["BT", f"/F1 {size} Tf", f"{leading:.2f} TL", f"{x} {y_start:.2f} Td"]
    for ln in lines:
        parts.append(f"({_pdf_escape(ln)}) Tj")
        parts.append("T*")
    parts.append("ET")
    if footer:
        parts += ["BT", f"/F1 {footer_size} Tf",
                  f"{x} {footer_y:.2f} Td",
                  f"({_pdf_escape(footer)}) Tj", "ET"]
    return "\n".join(parts).encode("latin-1", "replace")


def write_pdf(path, lines, footer_text, *, font_size=9, landscape=True):
    """Render `lines` to a multi-page PDF.

    `lines` are laid out in order (already including the report's top header
    line). On every page after the first, `footer_text` plus a page counter is
    printed in the footer.
    """
    page_w, page_h = (792, 612) if landscape else (612, 792)
    margin = 36
    leading = font_size * 1.25
    footer_size = max(7, font_size - 2)
    x = margin
    y_top = page_h - margin - font_size      # first text baseline
    footer_y = 18                            # footer baseline, below the margin

    lines_per_page = int((y_top - margin) / leading) + 1
    chunks = [lines[i:i + lines_per_page]
              for i in range(0, len(lines), lines_per_page)] or [[]]
    n = len(chunks)

    obj = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>",
    }
    page_nums = []
    next_num = 4
    for pi, chunk in enumerate(chunks):
        footer = (f"{footer_text}    page {pi + 1} of {n}"
                  if pi > 0 and footer_text else None)
        stream = _pdf_content_stream(
            chunk, footer, x=x, y_start=y_top, leading=leading, size=font_size,
            footer_y=footer_y, footer_size=footer_size,
        )
        content_num, page_num = next_num, next_num + 1
        next_num += 2
        obj[content_num] = (f"<< /Length {len(stream)} >>\nstream\n"
                            .encode("latin-1") + stream + b"\nendstream")
        obj[page_num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_w} {page_h}] "
            f"/Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {content_num} 0 R >>").encode("latin-1")
        page_nums.append(page_num)

    kids = " ".join(f"{p} 0 R" for p in page_nums)
    obj[2] = f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode("latin-1")

    max_num = next_num - 1
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in range(1, max_num + 1):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode("latin-1") + obj[num] + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {max_num + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for num in range(1, max_num + 1):
        out += f"{offsets[num]:010d} 00000 n \n".encode("latin-1")
    out += b"trailer\n" + f"<< /Size {max_num + 1} /Root 1 0 R >>\n".encode("latin-1")
    out += f"startxref\n{xref_pos}\n".encode("latin-1") + b"%%EOF\n"
    with open(path, "wb") as f:
        f.write(out)


def _summary_row(label, s):
    row = [label, round(s["mean"]), round(s["median"])]
    for lvl in (80, 90, 95, 99):
        row += [round(s[lvl][0]), round(s[lvl][1])]
    return row


def write_csv(path, *, header_line, params_line, end_real, end_nom,
              worst_1yr, worst_5yr, payout_title, payout, age):
    """Write the ending-balance summary and per-year payout table to CSV."""
    ci_cols = ["ci80_lo", "ci80_hi", "ci90_lo", "ci90_hi",
               "ci95_lo", "ci95_hi", "ci99_lo", "ci99_hi"]
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([header_line])
        w.writerow([params_line])
        w.writerow([])
        w.writerow(["Ending balance summary"])
        w.writerow(["basis", "mean", "median"] + ci_cols)
        w.writerow(_summary_row("today's dollars", summarize(end_real)))
        w.writerow(_summary_row("nominal dollars", summarize(end_nom)))
        w.writerow([])
        w.writerow(["worst 1-yr real return", f"{worst_1yr:.4f}"])
        if worst_5yr is not None:
            w.writerow(["worst 5-yr real return (cumulative)", f"{worst_5yr:.4f}"])
        w.writerow([])
        w.writerow([payout_title])
        w.writerow(["year", "age", "mean", "median"] + ci_cols)
        for t in range(payout.shape[1]):
            stats = _summary_row("", summarize(payout[:, t]))
            w.writerow([t + 1, age + t] + stats[1:])


def _prompt_and_export(pdf_body, footer_text, csv_kwargs):
    """Interactively offer to save the report to a PDF or CSV file."""
    if not sys.stdin.isatty():
        return
    while True:
        try:
            choice = input("\nSave output to a file? [PDF / csv / exit]: ").strip().lower()
        except EOFError:
            return
        if choice in ("", "exit", "quit", "q", "e"):
            return
        if choice == "pdf":
            path = (input("PDF filename [montecarlo_report.pdf]: ").strip()
                    or "montecarlo_report.pdf")
            write_pdf(path, pdf_body, footer_text)
            print(f"wrote {path}")
        elif choice == "csv":
            path = (input("CSV filename [montecarlo_report.csv]: ").strip()
                    or "montecarlo_report.csv")
            write_csv(path, **csv_kwargs)
            print(f"wrote {path}")
        else:
            print("Please type PDF, csv, or exit.")


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
        jrm, end_nom, end_real, pay_nom, pay_real, equities, inflations = run(
            amount=args.amount, age=args.age, gender=args.gender, state=args.state,
            joint_age=args.joint_age, joint_gender=args.joint_gender,
            sims=args.sims, years=args.years, model=args.model,
            block_length=args.block_length, seed=args.seed,
        )
    except (annuity_quote.QuoteError, urllib.error.URLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    elapsed = time.time() - t0

    worst_1yr, worst_5yr = worst_real_returns(equities, inflations)

    model_summary = jrm.summary()
    params_line = (
        f"{args.sims:,} simulations x {args.years} years  "
        f"(amount ${args.amount:,}, age {args.age} {args.gender}, {args.state}"
        + (f", joint {args.joint_age} {args.joint_gender}" if args.joint_age else "")
        + f")   [{elapsed:.1f}s]")

    real_block = _balance_block_lines(
        "Ending balance - today's dollars", end_real,
        extras=_worst_return_lines(worst_1yr, worst_5yr))
    nom_block = _balance_block_lines("Ending balance - nominal dollars", end_nom)

    pct_below_start = 100.0 * np.mean(end_real < args.amount)
    pct_below_half = 100.0 * np.mean(end_real < args.amount * 0.5)
    downside = (f"Paths ending below starting amount (real): {pct_below_start:.1f}%   "
                f"below half of it: {pct_below_half:.1f}%")

    if args.nominal:
        payout_title = "Annual payout by year - nominal dollars"
        payout = pay_nom
    else:
        payout_title = "Annual payout by year - today's dollars"
        payout = pay_real
    payout_lines = _payout_table_lines(payout_title, payout, args.age)

    # ----- stdout report (balance blocks stacked) -----
    print(model_summary)
    print()
    print(params_line)
    print()
    for ln in real_block:
        print(ln)
    print()
    for ln in nom_block:
        print(ln)
    print()
    print(downside)
    print()
    for ln in payout_lines:
        print(ln)

    # ----- offer file export -----
    user = getpass.getuser()
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    header_line = f"{user}    {stamp}"
    pdf_body = (
        [header_line, "", *model_summary.split("\n"), "", params_line, ""]
        + _side_by_side(real_block, nom_block)
        + ["", downside, ""]
        + payout_lines
    )
    csv_kwargs = dict(
        header_line=header_line, params_line=params_line,
        end_real=end_real, end_nom=end_nom,
        worst_1yr=worst_1yr, worst_5yr=worst_5yr,
        payout_title=payout_title, payout=payout, age=args.age,
    )
    _prompt_and_export(pdf_body, header_line, csv_kwargs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
