# Small-site production profile: one process keeps SQLite + in-memory rate limit coherent.
bind = "127.0.0.1:8008"
worker_class = "gthread"
workers = 1
threads = 4
timeout = 120
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
capture_output = True
