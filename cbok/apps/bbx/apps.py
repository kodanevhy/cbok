from django.apps import AppConfig


class BbxConfig(AppConfig):
    name = 'cbok.apps.bbx'

    def ready(self):
        from cbok import batch
        batch.run_all()
