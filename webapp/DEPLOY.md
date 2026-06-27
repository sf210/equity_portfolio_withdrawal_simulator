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
* Add your SSH key during creation (it lands in root's `authorized_keys`).
* Point a **DNS A/AAAA record** for your domain (e.g. `montecarlo.example.com`)
  at the Linode's public IP. The rest assumes that name resolves.

SSH in as root to begin.

## 2. Harden access (admin user + SSH)

Don't administer the box as root over SSH. Create a normal **login user with
sudo** for yourself, move your key to it, then lock SSH down. Keep your original
root session open until the new login is proven, so a misstep can't lock you out.

Create the admin user and grant sudo (run as root):

```bash
adduser sfiete                 # sets a password; fill the prompts
usermod -aG sudo sfiete
```

Install your SSH public key for that user. Easiest is from your **local**
machine (works while password login is still on):

```bash
ssh-copy-id -o PubkeyAuthentication=no -i ~/.ssh/id_ed25519.pub sfiete@<ip>
```

`-o PubkeyAuthentication=no` forces a password prompt. Without it, an agent
holding several keys can exhaust the server's `MaxAuthTries` (default 6) with key
offers and disconnect with *"Too many authentication failures"* before reaching
password auth.

If `ssh-copy-id` reports `cannot create .ssh/authorized_keys: Permission
denied`, the user's home/`.ssh` is owned by root — fix ownership as root and
retry:

```bash
chown -R sfiete:sfiete /home/sfiete
chmod 700 /home/sfiete /home/sfiete/.ssh
```

Confirm key login and sudo work (from a **new** terminal — do not close root yet):

```bash
ssh -o IdentitiesOnly=yes -i ~/.ssh/id_ed25519 sfiete@<ip>
sudo -v        # must succeed
```

Now lock SSH down. Edit `/etc/ssh/sshd_config` (or add
`/etc/ssh/sshd_config.d/99-hardening.conf`):

```
PermitRootLogin no
PasswordAuthentication no
```

Validate the config, then restart (the service is `ssh` on Ubuntu 24.04):

```bash
sudo sshd -t && sudo systemctl restart ssh
```

`sshd -t` must pass before the restart. Then verify in a new terminal that
`ssh sfiete@<ip>` still works and `ssh root@<ip>` is refused — only then close
your original root session.

Turn on the firewall now, allowing only SSH (you'll open the web ports later):

```bash
sudo apt update && sudo apt install -y ufw
sudo ufw allow OpenSSH
sudo ufw --force enable
```

> Tip: to avoid the `MaxAuthTries` problem on every connect, add a host entry to
> your **local** `~/.ssh/config`:
> ```
> Host montecarlo
>     HostName <ip>
>     User sfiete
>     IdentityFile ~/.ssh/id_ed25519
>     IdentitiesOnly yes
> ```
> Then just `ssh montecarlo`.

## 3. Create the service account

A separate, **unprivileged, non-login** account owns and runs the app — never
your sudo user, never root (run as root or with sudo):

```bash
adduser --system --group --home /opt/montecarlo montecarlo
```

* `--system` → low-UID account with **no password** and a `nologin` shell, so it
  cannot be logged into or SSH'd to. It exists only to run the app.
* `--group` → also creates the matching `montecarlo` group the systemd unit uses.
* `--home /opt/montecarlo` → its home is where the code will live.

Never give it sudo. Verify it came out locked down:

```bash
getent passwd montecarlo | cut -d: -f7    # shell -> /usr/sbin/nologin
groups montecarlo                          # -> montecarlo only (no sudo)
passwd -S montecarlo                        # -> L (locked password)
```

## 4. System packages

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-venv python3-pip git nginx
```

Enable automatic security updates and SSH brute-force protection:

```bash
sudo apt install -y unattended-upgrades fail2ban
sudo dpkg-reconfigure -plow unattended-upgrades   # choose "Yes"
sudo systemctl enable --now fail2ban
```

`tkinter` is **not** needed on the server — the web app never imports the
desktop GUI. matplotlib renders headlessly (the `Agg` backend).

## 5. Get the code

```bash
cd /opt
sudo git clone https://github.com/sf210/equity_portfolio_withdrawal_simulator.git montecarlo
cd montecarlo
sudo chown -R montecarlo:montecarlo /opt/montecarlo
```

## 6. Python environment

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

## 7. Run it under systemd

```bash
sudo cp webapp/deploy/montecarlo-web.service /etc/systemd/system/
# Review the Environment= caps/limits in that file and adjust to taste.
sudo systemctl daemon-reload
sudo systemctl enable --now montecarlo-web
sudo systemctl status montecarlo-web        # should be active (running)
sudo journalctl -u montecarlo-web -f        # live logs
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

## 8. nginx reverse proxy

```bash
sudo cp webapp/deploy/nginx-montecarlo.conf /etc/nginx/sites-available/montecarlo
# Edit the file: replace example.com with your domain (server_name in BOTH blocks).
sudo sed -i 's/example\.com/montecarlo.example.com/g' \
    /etc/nginx/sites-available/montecarlo
sudo ln -s /etc/nginx/sites-available/montecarlo /etc/nginx/sites-enabled/montecarlo
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

At this point `http://montecarlo.example.com/` serves the app over plain HTTP.
The config ships HTTP-only; certbot adds HTTPS in §10.

## 9. Open the firewall for the web

You already enabled ufw for SSH in §2; now allow HTTP/HTTPS. **Do this before
certbot** — Let's Encrypt validates by connecting to port 80, so it must be
reachable first:

```bash
sudo ufw allow 'Nginx Full'        # 80 + 443
sudo ufw status
```

Gunicorn listens only on `127.0.0.1`, so it is not reachable from the internet
except through nginx.

## 10. TLS with Let's Encrypt

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d montecarlo.example.com --redirect --agree-tos -m you@example.com
```

certbot adds a `listen 443 ssl` server block (with the certificate paths) to the
HTTP-only site, wires in the HTTP->HTTPS redirect (`--redirect`), and sets up
auto-renewal (`systemctl list-timers | grep certbot`). For a bare domain plus
`www`, pass both: `-d example.com -d www.example.com`.

## 11. Verify

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
sudo systemctl restart montecarlo-web
```

## Notes / hardening

* **Two accounts, two roles.** `sfiete` is your sudo login (key-only SSH);
  `montecarlo` is the unprivileged, non-login account that runs the app. The app
  account never has sudo, so an app compromise is not a root compromise.
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
