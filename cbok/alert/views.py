import logging
import threading

from django import http
from django.views.generic import base

from cbok.alert import manager
from cbok.alert import models
from cbok.notification.email import message

LOG = logging.getLogger(__name__)


class TopicView(base.View):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.alert_manager = manager.AlertManager()

    def post(self, request, **kwargs):
        """Create topic and initial derive"""

        cleaned_form = request.form
        topic_name = cleaned_form.cleaned_data['name']

        topic = models.Topic.objects.filter(name=topic_name).first()
        if topic and topic.in_progress:
            return http.JsonResponse(
                {'Already in progress': True}, status=403)

        if not topic:
            topic = models.Topic.objects.create(
                name=topic_name,
                status="created",
            )

        # TODO: only if the user hadn't created any topics 
        # message.send_welcome_email(["1923001710@qq.com"], "Mizar")

        threading.Thread(
            target=self.alert_manager.init_topic,
            kwargs={"topic": topic},
            daemon=True
        ).start()

        return http.JsonResponse({"In progress": True}, status=200)
