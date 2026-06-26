# Deploying the Monte Carlo web app on Linode

This walks through standing up the web front end (`webapp/app.py`) on a fresh
Linode running **Ubuntu 24.04 LTS**, served by **gunicorn** behind **nginx**
with a **Let's Encrypt** TLS certificate. The app is public and read-only: it
exposes a form, runs the simulation with hard input caps and local pricing only,
and returns the text report plus PDF/CSV downloads.

The pieces:

```
visitor ──HTTPS──▶ nginx (TLS, rate limit) ──HTTP──▶ gunicorn (127.0.0.1:8000) ──▶ Flask app
```

---

## 1. Create the Linode

* **Distribution:** Ubuntu 24.04 LTS.
* **Plan:** a 2 GB "Shared CPU" Nanode is enough for light traffic; the sims are
  CPU-bound, so more vCPUs = more concurrent runs. Start small, resize later.
* **Region:** closest to your users.
* Add your SSH key during creation.
* Point a **DNS A/AAAA record** for your domain (e.g. `montecarlo.example.com`)
  at the Linode's public IP. The rest assumes that name resolves.

SSH in as root and create an unprivileged user the service will run as:

```bash
adduser --system --group --home /opt/montecarlo montecarlo
```

## 2. System packages

```bash
apt update && apt upgrade -y
apt install -y python3-venv python3-pip git nginx
```

`tkinter` is **not** needed on the server — the web app never imports the
desktop GUI. matplotlib renders headlessly (the `Agg` backend).

## 3. Get the code

```bash
cd /opt
git clone https://github.com/sf210/equity_portfolio_withdrawal_simulator.git montecarlo
cd montecarlo
git checkout web-app          # until this branch is merged to master
chown -R montecarlo:montecarlo /opt/montecarlo
```

## 4. Python environment

```bash
sudo -u montecarlo python3 -m venv /opt/montecarlo/.venv
sudo -u montecarlo /opt/montecarlo/.venv/bin/pip install --upgrade pip
sudo -u montecarlo /opt/montecarlo/.venv/bin/pip install -r webapp/requirements-web.txt
```

Pre-build matplotlib's font cache once (otherwise the *first* PDF export is slow
while the cache builds — which looks like a hang):

```bash
sudo -u montecarlo mkdir -p /opt/montecarlo/.cache/matplotlib
sudo -u montecarlo env MPLCONFIGDIR=/opt/montecarlo/.cache/matplotlib \
    /opt/montecarlo/.venv/bin/python -c "import matplotlib.pyplot as p; p.figure()"
```

Smoke-test before wiring up systemd:

```bash
sudo -u montecarlo env MC_PROXY_FIX=0 \
    /opt/montecarlo/.venv/bin/gunicorn -c webapp/gunicorn_conf.py webapp.app:app &
curl -s localhost:8000/healthz        # -> ok
kill %1
```

## 5. Run it under systemd

```bash
cp webapp/deploy/montecarlo-web.service /etc/systemd/system/
# Review the Environment= caps/limits in that file and adjust to taste.
systemctl daemon-reload
systemctl enable --now montecarlo-web
systemctl status montecarlo-web        # should be active (running)
journalctl -u montecarlo-web -f        # live logs
```

The unit binds gunicorn to `127.0.0.1:8000` and sets `MPLCONFIGDIR` so the font
cache persists. Tunables (see the unit and `webapp/app.py`):

| Env var               | Default                | Meaning                              |
|-----------------------|------------------------|--------------------------------------|
| `MC_MAX_SIMS`         | 20000                  | hard cap on simulations per request  |
| `MC_MAX_YEARS`        | 60                     | hard cap on projection years         |
| `MC_MAX_CONCURRENT`   | 2                      | concurrent sims per worker process   |
| `MC_WORKERS`          | min(4, cores)          | gunicorn worker processes            |
| `MC_RATE_LIMITS`      | `60 per hour;10 per minute` | per-IP limits (Flask-Limiter)   |
| `MC_SLOT_TIMEOUT`     | 10                     | seconds to wait for a sim slot (else 503) |

## 6. nginx reverse proxy

```bash
cp webapp/deploy/nginx-montecarlo.conf /etc/nginx/sites-available/montecarlo
# Edit the file: replace example.com with your domain (server_name in BOTH blocks).
sed -i 's/example\.com/montecarlo.example.com/g' \
    /etc/nginx/sites-available/montecarlo
ln -s /etc/nginx/sites-available/montecarlo /etc/nginx/sites-enabled/montecarlo
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

At this point `http://montecarlo.example.com/` should redirect to HTTPS (which
isn't valid yet — that's the next step).

## 7. TLS with Let's Encrypt

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d montecarlo.example.com --redirect --agree-tos -m you@example.com
```

certbot fills in the `ssl_certificate*` lines in the 443 server block and sets
up auto-renewal (`systemctl list-timers | grep certbot`). Reload nginx if
prompted.

## 8. Firewall

```bash
apt install -y ufw
ufw allow OpenSSH
ufw allow 'Nginx Full'        # 80 + 443
ufw --force enable
```

Gunicorn listens only on `127.0.0.1`, so it is not reachable from the internet
except through nginx.

## 9. Verify

```bash
curl -s https://montecarlo.example.com/healthz            # -> ok
```

Then open the site in a browser, run a simulation, and download the PDF and CSV.

---

## Updating after a code change

```bash
cd /opt/montecarlo
sudo -u montecarlo git pull
sudo -u montecarlo /opt/montecarlo/.venv/bin/pip install -r webapp/requirements-web.txt
systemctl restart montecarlo-web
```

## Notes / hardening

* **Public + no auth by design.** Defence is depth: input caps in the app, a
  concurrency semaphore, per-IP rate limits in both Flask-Limiter and nginx, and
  a small `client_max_body_size`. There is no login and nothing is persisted.
* **No CSRF tokens.** The app stores no per-user state and performs no
  authenticated side effects, so cross-site POSTs can at most run a throwaway
  simulation. If you later add accounts or saved state, add CSRF protection.
* **Rate-limit storage.** Flask-Limiter defaults to in-memory (per worker). With
  multiple workers, run fewer workers or point `MC_LIMITER_STORAGE` at Redis for
  a shared, accurate limit.
* **Resource cap.** For a hard ceiling regardless of app logic, also set
  `MemoryMax=` / `CPUQuota=` in the systemd unit.
