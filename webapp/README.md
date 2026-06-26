# Web front end

A small Flask web version of the annuity-equivalent Monte Carlo simulator. It is
a thin layer over the existing engine (`montecarlo.build_report`) — the same
code the desktop GUI (`montecarlo_gui.py`) drives — so the simulation core is
shared and untouched.

What it exposes:

* a single-page input form mirroring the desktop GUI's fields,
* the text report rendered in the page,
* **Download PDF** (the consolidated graphical report) and **Download CSV**.

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
Let's Encrypt + systemd).

## Files

| Path                              | Purpose                                  |
|-----------------------------------|------------------------------------------|
| `app.py`                          | Flask app: routes, validation, caps      |
| `templates/index.html`            | the form + results page                  |
| `requirements-web.txt`            | engine + web stack dependencies          |
| `gunicorn_conf.py`                | gunicorn worker/timeout config           |
| `deploy/montecarlo-web.service`   | systemd unit                             |
| `deploy/nginx-montecarlo.conf`    | nginx reverse-proxy site                 |
| `DEPLOY.md`                       | Linode deployment guide                  |

## Configuration

All limits are environment variables read at startup; see the table in
[DEPLOY.md](DEPLOY.md#5-run-it-under-systemd) and the top of `app.py`.
