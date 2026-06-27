# Site analytics (visitors + geolocation)

Self-hosted usage tracking for the Monte Carlo web app using
**[GoAccess](https://goaccess.io)**, which parses nginx's access log into
visitor counts, unique visitors, top pages, and a country/city breakdown by IP.
No tracking JavaScript is added to the site and nothing is sent to a third
party — it reads logs you already have.

You get **both** views:

* an interactive **terminal dashboard** when you SSH in, and
* a **password-protected web report** at `https://<your-domain>/analytics/`,
  refreshed every 10 minutes by a systemd timer.

Stats are **persistent**: GoAccess keeps a small on-disk database so totals
accumulate over weeks/months even as nginx rotates and deletes old logs.

Geolocation uses the free **DB-IP City Lite** database (no account needed,
refreshed monthly, CC-BY-4.0).

---

## One-time setup (on the server)

### 1. Install GoAccess (with GeoIP2 support)

```bash
sudo apt install -y goaccess apache2-utils
goaccess --version | grep -i geoip      # must mention "GeoIP2"
```

If that line is missing (GeoIP2 not compiled in), use GoAccess's official repo
instead:

```bash
wget -qO - https://deb.goaccess.io/gnugpg.key \
    | gpg --dearmor | sudo tee /usr/share/keyrings/goaccess.gpg >/dev/null
echo "deb [signed-by=/usr/share/keyrings/goaccess.gpg arch=$(dpkg --print-architecture)] https://deb.goaccess.io/ $(lsb_release -cs) main" \
    | sudo tee /etc/apt/sources.list.d/goaccess.list
sudo apt update && sudo apt install -y goaccess
goaccess --version | grep -i geoip      # now shows GeoIP2
```

`apache2-utils` provides `htpasswd` for the web report's password.

### 2. Create the analytics output dir and password

```bash
sudo mkdir -p /var/www/analytics /var/lib/goaccess
sudo htpasswd -c /etc/nginx/.htpasswd-analytics admin     # prompts for a password
```

### 3. First run (also downloads the GeoIP database)

```bash
sudo /opt/montecarlo/webapp/analytics/update-analytics.sh
ls -la /var/www/analytics/index.html          # the report now exists
```

### 4. Schedule automatic refresh (every 10 min)

```bash
sudo cp /opt/montecarlo/webapp/analytics/goaccess-analytics.service /etc/systemd/system/
sudo cp /opt/montecarlo/webapp/analytics/goaccess-analytics.timer   /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now goaccess-analytics.timer
systemctl list-timers | grep goaccess          # confirm it's scheduled
```

### 5. Expose the report through nginx (behind the password)

Add the location block from `webapp/analytics/nginx-analytics.conf` **inside the
existing port-443 `server { ... }` block** in
`/etc/nginx/sites-available/montecarlo` (next to the other `location` lines),
then:

```bash
sudo nginx -t && sudo systemctl reload nginx
```

Visit **`https://<your-domain>/analytics/`** and log in with the credentials
from step 2.

---

## The terminal dashboard (on demand)

SSH in and run the live, interactive view (press `q` to quit):

```bash
sudo goaccess /var/log/nginx/access.log \
    --log-format=COMBINED \
    --geoip-database=/var/lib/goaccess/dbip-city-lite.mmdb \
    --persist --restore --db-path=/var/lib/goaccess
```

It reads the same persistent database as the scheduled job, so totals match the
web report. Geolocation lives under the **Visitor Hostnames and IPs** / country
panels.

---

## Notes

* **What "visitors" means.** GoAccess counts unique visitors per day by IP +
  user-agent and filters known crawlers (`--ignore-crawlers`). It's an
  approximation, not exact people — good enough for "how many and from where."
* **Geolocation accuracy.** Country-level is reliable; city-level is approximate
  (typical of all IP geolocation). The DB refreshes automatically each month.
* **Privacy.** `update-analytics.sh` runs with `--anonymize-ip`, so the report
  masks the host part of each address while still resolving location. Drop that
  flag in the script if you want to see full IPs. IP addresses are personal data
  in some jurisdictions — keep the report behind the password (it is by default)
  and consider adding a short privacy note to the site if traffic grows.
* **`/healthz` is excluded** already (nginx is configured with `access_log off`
  for it), so uptime probes don't inflate the numbers.
* **Attribution.** DB-IP Lite is CC-BY-4.0; GoAccess's footer credits the GeoIP
  source automatically.
