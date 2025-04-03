import logging

from django import http
from django.views.generic import base

from bbx.chrome_plugins.auto_login import manager as chrome_login_manager

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

        self.chrome_login_manager.ADDRESS = [address]
        self.chrome_login_manager.POSSIBLE_PASSWORD = [password]
        if not self.chrome_login_manager.try_login_and_persistent():
            return http.HttpResponseBadRequest()
        return http.JsonResponse({'code': 200})
