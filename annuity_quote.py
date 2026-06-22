#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Look up an estimated monthly life-annuity payment from immediateannuities.com.

Submits the homepage quote form (single POST to the "annuity-rates-step-1"
endpoint, which returns the quote table directly) and reads the dollar figure
in the row labelled "Life" -- i.e. the plain life-only payout (or, when a joint
beneficiary is supplied, the joint-life payout).

The site advertises these as "Average Estimated Quotes". Payments are assumed to
begin in 1 month, per the task spec.

Stdlib only (no requests/bs4): uses urllib + http.cookiejar + regex, so it runs
under any of the project's Python 3 venvs without extra packages.

Examples
--------
    python annuity_quote.py 100000 65 M FL
    python annuity_quote.py 250000 70 female CA --joint-age 68 --joint-gender M
"""

from __future__ import annotations

import argparse
import datetime as _dt
import http.cookiejar
import re
import sys
import urllib.parse
import urllib.request

HOME_URL = "https://www.immediateannuities.com/"
QUOTE_URL = "https://www.immediateannuities.com/information/annuity-rates-step-1.html"
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# "Income to Begin In: 1 month" maps to this select value on the site.
INCOME_START_1_MONTH = "0.08"

STATES = {
    "AK", "AL", "AR", "AZ", "CA", "CO", "CT", "DC", "DE", "FL", "GA", "HI",
    "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD", "ME", "MI", "MN",
    "MO", "MS", "MT", "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH",
    "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA",
    "WI", "WV", "WY", "OTHER",
}


class QuoteError(RuntimeError):
    """Raised when a quote could not be fetched or parsed."""


def _normalize_gender(value: str) -> str:
    v = value.strip().upper()
    if v in ("M", "MALE"):
        return "M"
    if v in ("F", "FEMALE"):
        return "F"
    raise argparse.ArgumentTypeError(f"gender must be M/F (male/female), got {value!r}")


def _normalize_state(value: str) -> str:
    v = value.strip().upper()
    if v not in STATES:
        raise argparse.ArgumentTypeError(
            f"state must be a 2-letter US state/DC code (or OTHER), got {value!r}"
        )
    return v


def _normalize_amount(value: str) -> int:
    # Accept a plain number (e.g. 100000) or a formatted one (e.g. $100,000).
    cleaned = re.sub(r"[\s$,]", "", str(value))
    try:
        amount = int(float(cleaned))
    except ValueError:
        raise argparse.ArgumentTypeError(f"amount must be a number, got {value!r}")
    if amount <= 0:
        raise argparse.ArgumentTypeError("amount must be positive")
    return amount


def _check_age(value: str) -> int:
    try:
        age = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"age must be an integer, got {value!r}")
    # The site's dropdowns only offer ages 40-90.
    if not 40 <= age <= 90:
        raise argparse.ArgumentTypeError("age must be between 40 and 90")
    return age


def _build_opener() -> urllib.request.OpenerDirector:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    opener.addheaders = [("User-Agent", USER_AGENT)]
    return opener


def _get(opener: urllib.request.OpenerDirector, url: str, data: bytes | None = None,
         referer: str | None = None) -> str:
    headers = {}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, data=data, headers=headers)
    with opener.open(req, timeout=30) as resp:
        raw = resp.read()
    return raw.decode("utf-8", errors="replace")


def _extract_token(html: str, name: str) -> str:
    m = re.search(
        rf'name="{re.escape(name)}"[^>]*\bvalue="([^"]*)"', html
    )
    if not m:
        # Some fields render value before name; try the reverse order too.
        m = re.search(
            rf'\bvalue="([^"]*)"[^>]*name="{re.escape(name)}"', html
        )
    if not m:
        raise QuoteError(f"could not find form token {name!r} on the homepage")
    return m.group(1)


def _parse_life_payment(html: str) -> str:
    """Return the dollar string in the row whose option label is exactly 'Life'."""
    # Row layout (per option):
    #   <div>Life&nbsp;<span class="tooltip">...</span></span></div></td><td>$685</td>
    # The "&nbsp;" right after "Life" distinguishes the life-only / joint-life row
    # from "Life & 5 Years Certain", "Life with Cash Refund", etc.
    m = re.search(
        r'<div>\s*Life&nbsp;.*?</div>\s*</td>\s*<td>\s*(\$[\d,]+)',
        html,
        re.DOTALL,
    )
    if not m:
        raise QuoteError(
            "could not locate the 'Life' payment in the quote page "
            "(site layout may have changed)"
        )
    return m.group(1)


def get_life_quote(
    amount: int,
    age: int,
    gender: str,
    state: str,
    joint_age: int | None = None,
    joint_gender: str | None = None,
) -> str:
    """Fetch the monthly 'Life' annuity payment as a dollar string (e.g. '$685')."""
    opener = _build_opener()

    home = _get(opener, HOME_URL)
    calc_sequence = _extract_token(home, "calc_sequence")
    # The site stamps the form with the current time; if it's missing for any
    # reason, fall back to "now" rather than failing.
    try:
        glitch_catcher = _extract_token(home, "glitch_catcher")
    except QuoteError:
        glitch_catcher = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    fields = {
        "annuity-data-1": "ar-start",
        "form_source": "H",
        "passed": "start",
        "income": "",
        "glitch_catcher": glitch_catcher,
        "calc_sequence": calc_sequence,
        "start_point": "/",
        "premium": str(amount),
        "income_start_date": INCOME_START_1_MONTH,
        "age": str(age),
        "gender": gender,
        "state": state,
        "joint_age": str(joint_age) if joint_age is not None else "0",
        "joint_gender": joint_gender if joint_gender is not None else "0",
        "sub1": "GET MY QUOTE!",
    }
    data = urllib.parse.urlencode(fields).encode("utf-8")
    page = _get(opener, QUOTE_URL, data=data, referer=HOME_URL)
    return _parse_life_payment(page)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Look up an estimated monthly life-annuity payment "
        "from immediateannuities.com (payments assumed to start in 1 month).",
    )
    parser.add_argument("amount", type=_normalize_amount,
                        help="amount to invest (premium), e.g. 100000 or 100,000 or $100,000")
    parser.add_argument("age", type=_check_age, help="age today (40-90)")
    parser.add_argument("gender", type=_normalize_gender, help="M/F (or male/female)")
    parser.add_argument("state", type=_normalize_state,
                        help="2-letter US state code, e.g. FL (or OTHER)")
    parser.add_argument("--joint-age", type=_check_age, default=None,
                        help="optional joint beneficiary age (40-90)")
    parser.add_argument("--joint-gender", type=_normalize_gender, default=None,
                        help="optional joint beneficiary gender (M/F)")
    args = parser.parse_args(argv)

    if (args.joint_age is None) != (args.joint_gender is None):
        parser.error("--joint-age and --joint-gender must be given together")

    try:
        payment = get_life_quote(
            amount=args.amount,
            age=args.age,
            gender=args.gender,
            state=args.state,
            joint_age=args.joint_age,
            joint_gender=args.joint_gender,
        )
    except (QuoteError, urllib.error.URLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Emit just the number (no "$", commas, or label) so it pipes cleanly.
    print(re.sub(r"[$,]", "", payment))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
