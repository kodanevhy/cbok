import sys

from django.apps import AppConfig


class BbxConfig(AppConfig):
    name = 'cbok.apps.bbx'

    def ready(self):
        if "runserver" in sys.argv:
            from cbok import batch
            batch.run_all()
