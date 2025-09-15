import logging

from django import http
from django.views.generic import base

from user import manager

LOG = logging.getLogger(__name__)


class UserView(base.View):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.user_manager = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.user_manager = manager.UserManager()

    def get(self, request):
        username = request.GET.get('username')
        user = self.user_manager.get(username)
        return http.JsonResponse({'username': user.username})

    def post(self, request, **kwargs):
        if not self.user_manager.is_authenticated(request.user):
            return http.JsonResponse({'not login': True})

        cleaned_form = request.form
        username = cleaned_form.cleaned_data['username']
        password = cleaned_form.cleaned_data['password']
        create_kwargs = {'username': username, 'password': password}

        self.user_manager.create(create_kwargs)
        return http.JsonResponse({'register success': True})


class LoginView(base.View):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.user_manager = None

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.user_manager = manager.UserManager()

    def post(self, request, **kwargs):
        if self.user_manager.is_authenticated(request.user):
            return http.JsonResponse({'repeated success': True})

        cleaned_form = request.form
        # TODO: support email login
        username = cleaned_form.cleaned_data['username']
        password = cleaned_form.cleaned_data['password']
        login_kwargs = {'username': username, 'password': password}
        self.user_manager.login(request, login_kwargs)

        return http.JsonResponse({'success': True})
