#root/gunicorn.conf.py
bind = "0.0.0.0:8000"
workers = 3
worker_class = "gthread"
threads = 4
timeout = 60
keepalive = 5
accesslog = "-"