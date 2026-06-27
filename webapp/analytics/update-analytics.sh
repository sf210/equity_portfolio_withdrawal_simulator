#!/usr/bin/env bash
# Refresh the GoAccess analytics for the Monte Carlo web app.
#
# Builds/updates a persistent stats database from nginx's access log and writes a
# static HTML report. Run periodically (see goaccess-analytics.timer) and also
# usable by hand. Reads the access log, so run as root (or a user in the `adm`
# group). See webapp/ANALYTICS.md.
set -euo pipefail

DB_DIR="${MC_ANALYTICS_DB:-/var/lib/goaccess}"      # persistent stats + GeoIP db
OUT_DIR="${MC_ANALYTICS_OUT:-/var/www/analytics}"   # served (behind auth) by nginx
OUT="$OUT_DIR/index.html"
LOG="${MC_ANALYTICS_LOG:-/var/log/nginx/access.log}"
GEO_DB="$DB_DIR/dbip-city-lite.mmdb"
STAMP="$DB_DIR/.geoip-month"

mkdir -p "$DB_DIR" "$OUT_DIR"

# DB-IP City Lite: free, no account, refreshed monthly (CC-BY-4.0). Only
# download when we don't already have this month's copy. Fall back to last
# month early in the month before the new file is published.
month="$(date +%Y-%m)"
if [[ ! -f "$GEO_DB" || "$(cat "$STAMP" 2>/dev/null || true)" != "$month" ]]; then
    for m in "$month" "$(date -d 'last month' +%Y-%m 2>/dev/null || true)"; do
        [[ -n "$m" ]] || continue
        url="https://download.db-ip.com/free/dbip-city-lite-${m}.mmdb.gz"
        if curl -fsSL "$url" -o "$GEO_DB.gz"; then
            gunzip -f "$GEO_DB.gz"
            echo "$month" > "$STAMP"
            break
        fi
    done
    rm -f "$GEO_DB.gz" 2>/dev/null || true
fi

geo_opt=()
[[ -f "$GEO_DB" ]] && geo_opt=(--geoip-database="$GEO_DB")

# --persist/--restore keep cumulative history in $DB_DIR across runs and log
# rotations (GoAccess processes only new lines incrementally). --anonymize-ip
# masks the host part in the report while still allowing country/region lookup;
# drop it if you want to see full visitor IPs.
goaccess "$LOG" \
    --log-format=COMBINED \
    "${geo_opt[@]}" \
    --persist --restore --db-path="$DB_DIR" \
    --anonymize-ip \
    --ignore-crawlers \
    --html-report-title="Monte Carlo site analytics" \
    -o "$OUT"
