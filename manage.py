#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import logging
import os
import platform
import sys

import eventlet

from cbok import batch

LOG = logging.getLogger()
LOG.setLevel(logging.INFO)


class FlushStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()

if not LOG.handlers:
    ch = FlushStreamHandler(sys.stdout)
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s][%(threadName)s] %(message)s'
    )
    ch.setFormatter(formatter)
    LOG.addHandler(ch)


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cbok.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    use_eventlet = not platform.system() == "Darwin"
    if use_eventlet:
        eventlet.monkey_patch()

    if len(sys.argv) > 1 and sys.argv[1] == "runserver":
        batch.run_all(use_eventlet=use_eventlet)

    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
