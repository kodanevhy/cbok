from django.contrib.auth import authenticate
from django.contrib.auth import login

from user import exceptions
from user import models


class UserManager:
    def __init__(self):
        pass

    def is_authenticated(self, user):
        return user.is_authenticated

    def get(self, username):
        return models.UserProfile.objects.get(username=username)

    def create(self, create_kwargs):
        username = create_kwargs['username']
        password = create_kwargs['password']
        if models.UserProfile.objects.filter(username=username):
            raise exceptions.UserExists(username=username)

        user_profile = models.UserProfile()
        user_profile.username = username
        user_profile.password = password
        user_profile.save()

    def login(self, request, login_kwargs):
        username = login_kwargs['username']
        password = login_kwargs['password']
        user = authenticate(request, username=username, password=password)

        csrf = request.META.get('CSRF_COOKIE')

        def _rollback_csrf_token():
            # `login` will rotate the token in cookie when succeeded,  but we
            # hope that the token will not change during its validity period.
            request.META['CSRF_COOKIE'] = csrf
            # do not reset csrf into response for storing in browser cookie
            request.META['CSRF_COOKIE_USED'] = True

        if user and user.is_active:
            login(request, user)
            _rollback_csrf_token()
