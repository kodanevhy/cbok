import logging
import os

from django import http
from django.views.generic import base

from cbok.apps.bbx.chrome_plugins.auto_login.server import manager as \
    chrome_login_manager

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
        """Retreive passphrase"""
        passphrase_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'chrome_plugins/auto_login/passphrase')

        result = []

        if not os.path.exists(passphrase_path):
            return http.JsonResponse({"code": 404, "result": result})

        with open(passphrase_path, "r") as f:
            for line in f:
                parts = line.strip().split(",")
                if len(parts) == 3:
                    result.append({
                        "ip": parts[0].strip(),
                        "user": parts[1].strip(),
                        "password": parts[2].strip()
                    })
        return http.JsonResponse({"code": 200, "result": result})
