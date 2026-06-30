#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""A small Flask front end for the annuity-equivalent Monte Carlo simulator.

This is a thin web layer over the existing engine: it validates a posted form,
calls ``montecarlo.build_report`` (the same entry point the desktop GUI uses),
renders the text report in a page, and offers the PDF/CSV exports as downloads.
The simulation core is untouched.

Design notes for a *public* deployment:

* The path count is fixed (``FIXED_SIMS``) and the other inputs are hard-capped
  (``MAX_YEARS`` / ``MAX_BLOCK_LENGTH``) so a visitor cannot ask for an unbounded
  amount of CPU work.
* The pricing source is forced to ``local`` -- no per-request outbound web
  fetches (the ``site`` quote source is never exposed here).
* A process-wide semaphore caps how many simulations run at once; excess
  requests get a 503 instead of piling onto the CPU.
* Per-IP rate limiting is applied when Flask-Limiter is installed.

Runs (each path runs the full simulation once and is cached briefly so the
matching download does not recompute):

    GET  /            -> the input form
    POST /run         -> validate + simulate, render the text report
    POST /export.pdf  -> the consolidated graphical PDF report (download)
    POST /export.csv  -> the summary CSV (download)
    GET  /healthz     -> liveness probe for the reverse proxy / uptime checks
"""

from __future__ import annotations

import csv
import io
import os
import pathlib
import secrets
import sys
import tempfile
import threading
from datetime import datetime
from functools import lru_cache

import numpy as np

# The engine modules live in the repository root, one level up from webapp/;
# webapp's own modules (figures.py) live in _HERE. Put both on the path so the
# app imports the same way whether launched as webapp.app:app or webapp/app.py.
_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in (str(_ROOT), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import annuity_quote  # noqa: E402  (path set up above)
import montecarlo as mc  # noqa: E402
from global_market_data import GlobalDataMissing as _GlobalDataMissing  # noqa: E402

from flask import (  # noqa: E402
    Flask, Response, abort, render_template, request, send_file,
)

# --------------------------------------------------------------------------- #
# Limits (override via environment on the server).
# --------------------------------------------------------------------------- #
# Number of paths is fixed (not a user input) to bound per-request CPU.
FIXED_SIMS = int(os.environ.get("MC_SIMS", "5000"))
MAX_YEARS = int(os.environ.get("MC_MAX_YEARS", "60"))
MAX_BLOCK_LENGTH = int(os.environ.get("MC_MAX_BLOCK_LENGTH", "50"))
MAX_AMOUNT = int(os.environ.get("MC_MAX_AMOUNT", str(1_000_000_000_000)))
# Concurrent simulations across this worker process.
MAX_CONCURRENT = int(os.environ.get("MC_MAX_CONCURRENT", "2"))
# Seconds to wait for a free simulation slot before giving up with 503.
SLOT_TIMEOUT = float(os.environ.get("MC_SLOT_TIMEOUT", "10"))

_SIM_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT)

# Equity-return sample offered (the engine also knows these); local pricing only.
MODELS = ["us", "global", "postwar"]
GENDERS = ["M", "F"]
STATES = sorted(annuity_quote.STATES)

# Defaults shown on a fresh form (mirrors the desktop GUI).
DEFAULTS = {
    "amount": "1,000,000", "sims": "5000", "age": "65", "years": "35",
    "gender": "M", "model": "global", "state": "FL", "block_length": "5",
    "joint_age": "65", "joint_gender": "F", "upper_bound": "1.5",
    "lower_bound": "", "seed": "42", "inflation": "",
    "interest": str(mc.rate_model.DEFAULT_INITIAL_RATE),
    "dynamic": "", "improvement": "on",
}

app = Flask(__name__)

# Behind nginx, trust one layer of X-Forwarded-* so request.remote_addr (and
# thus per-IP rate limiting) reflects the real client, not 127.0.0.1. Enabled
# by default; set MC_PROXY_FIX=0 when running without a reverse proxy.
if os.environ.get("MC_PROXY_FIX", "1") != "0":
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


# --------------------------------------------------------------------------- #
# Optional per-IP rate limiting (no-op if Flask-Limiter is absent).
# --------------------------------------------------------------------------- #
def _install_limiter(flask_app):
    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address
    except ImportError:
        return None
    default = os.environ.get("MC_RATE_LIMITS", "60 per hour;10 per minute")
    return Limiter(
        key_func=get_remote_address, app=flask_app,
        default_limits=[s.strip() for s in default.split(";") if s.strip()],
        storage_uri=os.environ.get("MC_LIMITER_STORAGE", "memory://"),
    )


limiter = _install_limiter(app)


# --------------------------------------------------------------------------- #
# Form parsing / validation (mirrors the GUI's _collect_params, with caps).
# --------------------------------------------------------------------------- #
class FormError(ValueError):
    """A user-facing validation problem with the posted form."""


def _opt(form, name):
    """Return a stripped value, or None when the field is blank/absent."""
    v = (form.get(name) or "").strip()
    return v or None


def _float_field(form, name, default=0.0):
    v = _opt(form, name)
    if v is None:
        return default
    try:
        return float(v)
    except ValueError:
        raise FormError(f"{name} must be a number, got {v!r}")


def parse_form(form) -> dict:
    """Validate the posted form into kwargs for ``montecarlo.build_report``.

    Raises FormError (with a message safe to show the user) on bad input.
    Enforces the public-deployment caps and forces local pricing.
    """
    try:
        amount = annuity_quote._normalize_amount(form.get("amount", ""))
        age = annuity_quote._check_age(form.get("age", ""))
        gender = annuity_quote._normalize_gender(form.get("gender", ""))
        state = annuity_quote._normalize_state(form.get("state", ""))
    except Exception as exc:  # argparse.ArgumentTypeError et al.
        raise FormError(str(exc))

    if amount > MAX_AMOUNT:
        raise FormError(f"amount must be at most {MAX_AMOUNT:,}.")

    ja = _opt(form, "joint_age")
    jg = _opt(form, "joint_gender")
    try:
        joint_age = annuity_quote._check_age(ja) if ja is not None else None
        joint_gender = (annuity_quote._normalize_gender(jg)
                        if jg is not None else None)
    except Exception as exc:
        raise FormError(str(exc))
    if (joint_age is None) != (joint_gender is None):
        raise FormError("Joint age and joint gender must be given together.")

    sims = FIXED_SIMS  # not a user input
    try:
        years = int(form.get("years", ""))
        block_length = int(form.get("block_length", "") or "0")
    except ValueError:
        raise FormError("Years and Block length must be whole numbers.")
    if not 1 <= years <= MAX_YEARS:
        raise FormError(f"Years must be between 1 and {MAX_YEARS}.")
    if not 1 <= block_length <= MAX_BLOCK_LENGTH:
        raise FormError(f"Block length must be between 1 and {MAX_BLOCK_LENGTH}.")

    model = form.get("model", "global")
    if model not in MODELS:
        raise FormError(f"Model must be one of {', '.join(MODELS)}.")

    inflation = _float_field(form, "inflation", mc.wp.DEFAULT_INFLATION)
    if inflation <= -1:
        raise FormError("Inflation must be greater than -100%.")
    interest = _float_field(form, "interest", mc.rate_model.DEFAULT_INITIAL_RATE)
    if interest <= -1:
        raise FormError("Interest rate must be greater than -100%.")

    improvement = bool(_opt(form, "improvement"))
    dynamic = bool(_opt(form, "dynamic"))
    if dynamic and model != "us":
        raise FormError("Dynamic inflation + rate is only available with the "
                        "United States return sample.")

    upper = _float_field(form, "upper_bound", None) if _opt(form, "upper_bound") else None
    lower = _float_field(form, "lower_bound", None) if _opt(form, "lower_bound") else None
    if upper is not None and upper <= 0:
        raise FormError("Upper bound must be positive.")
    if lower is not None and lower < 0:
        raise FormError("Lower bound must not be negative.")
    if upper is not None and lower is not None and lower > upper:
        raise FormError("Lower bound must not exceed upper bound.")

    # Resolve the seed up front: if blank, pick one now so the report shown on
    # screen and the matching PDF/CSV download describe the exact same run.
    seed_text = _opt(form, "seed")
    if seed_text is not None:
        try:
            seed = int(seed_text)
        except ValueError:
            raise FormError(f"Seed must be a whole number, got {seed_text!r}.")
    else:
        seed = secrets.randbelow(2**31)

    # Public deployment: local pricing only, never live site quotes.
    return dict(
        amount=amount, age=age, gender=gender, state=state,
        joint_age=joint_age, joint_gender=joint_gender,
        sims=sims, years=years, model=model,
        block_length=block_length, seed=seed,
        inflation=inflation, upper_bound=upper, lower_bound=lower,
        quotes="local", interest=interest, improvement=improvement,
        dynamic_rates=dynamic, initial_rate=interest,
    )


# --------------------------------------------------------------------------- #
# Simulation (cached so the page render and its download don't recompute).
# --------------------------------------------------------------------------- #
def _params_key(params: dict) -> tuple:
    """A hashable canonical key for the parameter set (for the LRU cache)."""
    return tuple(sorted(params.items()))


@lru_cache(maxsize=32)
def _run_keyed(key: tuple):
    params = dict(key)
    return mc.build_report(**params)


def _simulate(params: dict):
    """Run (or fetch the cached) report bundle under the concurrency cap.

    The lru_cache means a download that follows its own /run reuses the result
    instead of recomputing. We still take a concurrency slot for the call: a
    cache hit returns almost immediately, so the slot is held only briefly.
    """
    key = _params_key(params)
    if not _SIM_SLOTS.acquire(timeout=SLOT_TIMEOUT):
        abort(503, "The server is busy running other simulations. "
                   "Please try again in a moment.")
    try:
        return _run_keyed(key)
    finally:
        _SIM_SLOTS.release()


def _hidden_fields(params: dict) -> dict:
    """The exact run parameters, as strings, to round-trip via hidden inputs."""
    return {
        "amount": str(params["amount"]), "age": str(params["age"]),
        "gender": params["gender"], "state": params["state"],
        "sims": str(params["sims"]), "years": str(params["years"]),
        "model": params["model"], "block_length": str(params["block_length"]),
        "joint_age": "" if params["joint_age"] is None else str(params["joint_age"]),
        "joint_gender": params["joint_gender"] or "",
        "upper_bound": "" if params["upper_bound"] is None else repr(params["upper_bound"]),
        "lower_bound": "" if params["lower_bound"] is None else repr(params["lower_bound"]),
        "seed": str(params["seed"]),
        "inflation": repr(params["inflation"]),
        "interest": repr(params["interest"]),
        "dynamic": "on" if params["dynamic_rates"] else "",
        "improvement": "on" if params["improvement"] else "",
    }


# --------------------------------------------------------------------------- #
# Report building: summary table, per-year withdrawal table, worst-loss lines.
# --------------------------------------------------------------------------- #
# Percentiles shown throughout the report.
PCTS = [1, 5, 25, 50, 75, 95, 99]
PCT_HEADERS = ["1st", "5th", "25th", "Median", "75th", "95th", "99th"]


def _money(v: float) -> str:
    a = abs(v)
    if a >= 1e6:
        return f"${v / 1e6:,.2f}M"
    if a >= 1e3:
        return f"${v / 1e3:,.0f}k"
    return f"${v:,.0f}"


def _pct(frac: float, decimals: int = 0) -> str:
    return f"{frac * 100:,.{decimals}f}%"


def _pcts(arr) -> list:
    return [float(np.percentile(arr, p)) for p in PCTS]


def _summary(data: dict) -> dict:
    """Portfolio summary split into a real section and a nominal section."""
    eq, infl = data["equities"], data["inflations"]
    n_years = eq.shape[1]
    total_nom = np.prod(1.0 + eq, axis=1) ** (1.0 / n_years) - 1.0
    total_real = np.prod((1.0 + eq) / (1.0 + infl), axis=1) ** (1.0 / n_years) - 1.0
    wd_nom = data["payouts_nominal"].mean(axis=1)
    wd_real = data["payouts_real"].mean(axis=1)

    def money_row(label, arr):
        return {"label": label, "cells": [_money(v) for v in _pcts(arr)]}

    def pct_row(label, arr, decimals=0):
        return {"label": label,
                "cells": [_pct(v, decimals) for v in _pcts(arr)]}

    real_rows = [
        money_row("Ending balance", data["end_real"]),
        pct_row("Total return (geo mean)", total_real, decimals=1),
        money_row("Mean annual withdrawal", wd_real),
    ]
    nominal_rows = [
        money_row("Ending balance", data["end_nom"]),
        pct_row("Total return (geo mean)", total_nom, decimals=1),
        money_row("Mean annual withdrawal", wd_nom),
    ]
    worst = {"one_yr": _pct(data["worst_1yr"]),
             "five_yr": None if data["worst_5yr"] is None else _pct(data["worst_5yr"])}
    return {"headers": PCT_HEADERS, "real": real_rows, "nominal": nominal_rows,
            "worst": worst}


def _withdrawal_rows(data: dict) -> dict:
    """Per-year withdrawal table (real $): mean, median, and percentiles."""
    pay = data["payouts_real"]
    age = data["age"]
    years = pay.shape[1]
    extra = [p for p in PCTS if p != 50]  # median shown separately
    headers = (["Year", "Age", "Mean", "Median"]
               + [("1st" if p == 1 else f"{p}th") for p in extra])
    rows = []
    for t in range(years):
        col = pay[:, t]
        cells = [_money(float(col.mean())), _money(float(np.median(col)))]
        cells += [_money(float(np.percentile(col, p))) for p in extra]
        rows.append({"year": t + 1, "age": age + t, "cells": cells})
    return {"headers": headers, "rows": rows}


def _withdrawal_csv(data: dict, params: dict) -> str:
    pay = data["payouts_real"]
    age = data["age"]
    extra = [p for p in PCTS if p != 50]
    buf = io.StringIO()
    w = csv.writer(buf)

    # Input assumptions and run date, one element per line, then a blank line.
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    assumptions = [
        ("Generated", stamp),
        ("Amount", params["amount"]),
        ("Age", params["age"]),
        ("Gender", params["gender"]),
        ("Joint age", "" if params["joint_age"] is None else params["joint_age"]),
        ("Joint gender", params["joint_gender"] or ""),
        ("Return sample", params["model"]),
        ("Years", params["years"]),
        ("Simulations", params["sims"]),
        ("Block length", params["block_length"]),
        ("Upper bound", "" if params["upper_bound"] is None else params["upper_bound"]),
        ("Lower bound", "" if params["lower_bound"] is None else params["lower_bound"]),
        ("Inflation", params["inflation"]),
        ("Interest rate", params["interest"]),
        ("Dynamic inflation + rate", params["dynamic_rates"]),
        ("Scale G2 improvement", params["improvement"]),
        ("Quotes", params["quotes"]),
        ("Seed", params["seed"]),
    ]
    for label, value in assumptions:
        w.writerow([label, value])
    w.writerow([])

    w.writerow(["Withdrawals by year (real, today's dollars)"])
    w.writerow(["year", "age", "mean", "median"] + [f"p{p}" for p in extra])
    for t in range(pay.shape[1]):
        col = pay[:, t]
        w.writerow([t + 1, age + t, round(float(col.mean())),
                    round(float(np.median(col)))]
                   + [round(float(np.percentile(col, p))) for p in extra])
    return buf.getvalue()


def _render(values, error=None, status=200, **extra):
    return render_template(
        "index.html", values=values, models=MODELS, genders=GENDERS,
        states=STATES, max_years=MAX_YEARS,
        error=error, **extra), status


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.route("/")
def index():
    return _render(DEFAULTS, report=None)[0]


@app.route("/run", methods=["POST"])
def run():
    try:
        params = parse_form(request.form)
    except FormError as exc:
        return _render(request.form, error=str(exc), report=None, status=400)

    try:
        _text, _csv_kwargs, data = _simulate(params)
    except _GlobalDataMissing:
        return _render(
            request.form, report=None, status=503,
            error="The global developed-markets dataset is not installed on this "
                  "server yet. Choose the 'United States' sample, or ask the "
                  "operator to run fetch_global_data.py.")

    import figures  # lazy: pulls in matplotlib only when a report is built
    return _render(
        request.form, report=True, params_line=data["params_line"],
        model_summary=data["model_summary"], figs=figures.build_figures(data),
        summary=_summary(data), wd_table=_withdrawal_rows(data),
        hidden=_hidden_fields(params))[0]


@app.route("/withdrawals.csv", methods=["POST"])
def withdrawals_csv():
    try:
        params = parse_form(request.form)
    except FormError as exc:
        abort(400, str(exc))
    try:
        _text, _csv_kwargs, data = _simulate(params)
    except _GlobalDataMissing:
        abort(503, "The global developed-markets dataset is not installed.")
    body = _withdrawal_csv(data, params).encode()
    return send_file(io.BytesIO(body), mimetype="text/csv", as_attachment=True,
                     download_name="withdrawals_by_year.csv")


@app.route("/license")
def license_text():
    path = _ROOT / "LICENSE"
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="text/plain", as_attachment=False,
                     download_name="LICENSE.txt")


# Reference documents shipped in the repo root, served inline (view in browser).
_DOCS = {"methodology": "METHODOLOGY.pdf", "motivation": "motivation.pdf"}


@app.route("/docs/<name>")
def docs(name):
    filename = _DOCS.get(name)
    if filename is None:
        abort(404)
    path = _ROOT / filename
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="application/pdf", as_attachment=False,
                     download_name=filename)


@app.route("/healthz")
def healthz():
    return Response("ok\n", mimetype="text/plain")


if __name__ == "__main__":
    # Development server only; production runs under gunicorn (see webapp/DEPLOY.md).
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=True)
