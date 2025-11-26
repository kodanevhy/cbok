import logging

from django import http
from django.views.generic import base

from cbok.apps.bbx.chrome_plugins.auto_login.server import manager as \
    chrome_login_manager
from cbok.apps.bbx.models import ChromePluginAutoLoginHostInfo


LOG = logging.getLogger(__name__)


class ChromePluginsView(base.View):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.chrome_login_manager = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.chrome_login_manager = chrome_login_manager.LoginManager()

    def post(self, request, **kwargs):
        """Persistent a record if login succeed."""
        cleaned_form = request.form
        address = cleaned_form.cleaned_data['address']
        password = cleaned_form.cleaned_data['password']

        if not self.chrome_login_manager.try_login_and_persistent(
            viewer_address=address, viewer_password=password):
            return http.HttpResponseBadRequest()
        return http.JsonResponse({'code': 200})

    def get(self, request, **kwargs):
        """Retrieve passphrase"""
        result = []

        hosts = ChromePluginAutoLoginHostInfo.objects.all()
        for host in hosts:
            result.append({
                "ip": host.ip_address,
                "user": host.username,
                "password": host.password
            })

        code = 200 if result else 404
        return http.JsonResponse({"code": code, "result": result})
