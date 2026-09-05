"""One warmed solver process with concurrent lightweight HTTP requests."""

import os

from deploy import configure_environment, warm_application

configure_environment()

bind = f"0.0.0.0:{os.environ.get('PORT', '10000')}"
workers = 1
worker_class = 'gthread'
threads = 4
timeout = 120
graceful_timeout = 30
keepalive = 5
max_requests = 2000
max_requests_jitter = 200
accesslog = '-'
errorlog = '-'
capture_output = True
worker_tmp_dir = '/tmp'
control_socket_disable = True


def post_worker_init(worker):
    # No request is served until tables and compiled kernels pass these checks.
    # A failed warmup fails the worker boot and therefore deployment readiness.
    warm_application(worker.wsgi)
