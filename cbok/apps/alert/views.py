import logging

from django import http
from django.views.generic import base

from cbok.apps.alert import manager

LOG = logging.getLogger(__name__)


class TopicView(base.View):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.alert_manager = manager.AlertManager()

    def post(self, request, **kwargs):
        """Create topic"""

        cleaned_form = request.form
        topic = cleaned_form.cleaned_data['name']

        # TODO: create topic, if success then return
        # TODO: async
        self.alert_manager.crawl(topic, first_track=True)
        return http.JsonResponse({'Topic tracked': True})
