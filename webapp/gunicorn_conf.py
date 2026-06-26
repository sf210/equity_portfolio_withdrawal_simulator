# Gunicorn configuration for the Monte Carlo web app.
# Run with:  gunicorn -c webapp/gunicorn_conf.py webapp.app:app
#
# The simulations are CPU-bound and run synchronously inside a request, so we
# use a small number of sync workers (roughly one per core) and a generous
# timeout to cover a max-size run plus PDF rendering.

import multiprocessing
import os

# Bind to localhost only; nginx terminates TLS and proxies to this socket.
bind = os.environ.get("MC_BIND", "127.0.0.1:8000")

# One worker per core (capped), each handling a couple of concurrent threads so
# a download that follows a run isn't blocked behind another visitor's sim.
workers = int(os.environ.get("MC_WORKERS", str(min(4, multiprocessing.cpu_count()))))
threads = int(os.environ.get("MC_THREADS", "4"))
worker_class = "gthread"

# A max-size simulation + PDF render must finish well within this.
timeout = int(os.environ.get("MC_TIMEOUT", "120"))
graceful_timeout = 30
keepalive = 5

# Recycle workers periodically to bound any memory growth from the result cache.
max_requests = int(os.environ.get("MC_MAX_REQUESTS", "500"))
max_requests_jitter = 50

accesslog = os.environ.get("MC_ACCESS_LOG", "-")   # stdout -> journald
errorlog = os.environ.get("MC_ERROR_LOG", "-")
loglevel = os.environ.get("MC_LOG_LEVEL", "info")
