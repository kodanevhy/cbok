import configparser
import os

import django
from django.apps import apps


def setup_django_for_tests():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cbok.settings")
    try:
        if not apps.ready:
            django.setup()
    except configparser.Error:
        return
