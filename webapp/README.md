# Web front end

A small Flask web version of the annuity-equivalent Monte Carlo simulator. It is
a thin layer over the existing engine (`montecarlo.build_report`) — the same
code the desktop GUI (`montecarlo_gui.py`) drives — so the simulation core is
shared and untouched.

What it exposes:

* a single-page input form mirroring the desktop GUI's fields, with a help
  pop-up next to each input explaining what it does and how it affects results;
* a graphical results report rendered in the page (server-side matplotlib PNGs):
  a portfolio-balance fan chart, a percentile summary table (1/5/10/50/90/95/98),
  a withdrawal fan chart, ending-balance and max-drawdown histograms, and a
  per-year withdrawal table — all in today's dollars;
* **Download PDF** (the browser prints the on-page report) and **Export table to
  CSV** (the per-year withdrawal table).

It is built for a **public, no-auth** deployment, so it differs from the desktop
app in three deliberate ways:

* inputs are hard-capped (`MC_MAX_SIMS`, `MC_MAX_YEARS`, `MC_MAX_BLOCK_LENGTH`),
* pricing is **local only** — the live `site` quote source is never exposed,
* concurrency is capped by a semaphore and requests are per-IP rate limited.

## Run locally (development)

From the repository root, with the project venv:

```bash
pip install -r webapp/requirements-web.txt
MC_PROXY_FIX=0 python webapp/app.py        # http://127.0.0.1:5000
```

or under gunicorn the way production runs it:

```bash
MC_PROXY_FIX=0 gunicorn -c webapp/gunicorn_conf.py webapp.app:app
```

## Deploy to a server

See [DEPLOY.md](DEPLOY.md) for a full Linode walkthrough (gunicorn + nginx +
Let's Encrypt + systemd), and [ANALYTICS.md](ANALYTICS.md) for self-hosted
visitor/geolocation tracking (GoAccess).

## Files

| Path                              | Purpose                                  |
|-----------------------------------|------------------------------------------|
| `app.py`                          | Flask app: routes, validation, caps      |
| `figures.py`                      | matplotlib report charts (base64 PNGs)   |
| `templates/index.html`            | the form + results page + help/print JS  |
| `requirements-web.txt`            | engine + web stack dependencies          |
| `gunicorn_conf.py`                | gunicorn worker/timeout config           |
| `deploy/montecarlo-web.service`   | systemd unit                             |
| `deploy/nginx-montecarlo.conf`    | nginx reverse-proxy site                 |
| `DEPLOY.md`                       | Linode deployment guide                  |
| `analytics/`                      | GoAccess analytics kit (script + timer)  |
| `ANALYTICS.md`                    | visitor/geolocation analytics guide      |

## Configuration

All limits are environment variables read at startup; see the table in
[DEPLOY.md](DEPLOY.md#5-run-it-under-systemd) and the top of `app.py`.
